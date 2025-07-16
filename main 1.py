import os
import ssl
import uvicorn
import logging
from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status, Query
from typing import Optional
from pydantic import BaseModel, EmailStr, SecretStr
from src.app.main import APITestGenerator
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from passlib.context import CryptContext
from datetime import datetime, timedelta
from jose import JWTError, jwt
from src.metrics.metrics_manager import RetrieveMetrics, save_metrics_to_mongo_from_csv
from pymongo import MongoClient
from bson import ObjectId
import traceback

#this is a test file

    def second dummy_function():
    """
    this is my pushed repo
    This is 2nd dummy function for testing purposes.
    It does nothing and returns None.
    """
    pass

#FILES TO IMPORT FROM GENIE
from src.services.user.user_service import UserService, users_collection
from src.auth.auth import AuthService
from src.config.config import settings
from src.models.User import EmailAuthPasswordForm, PasswordReset, RoleUpdate, UserRole
from src.models.Registeruser import RegisterUser
from src.utils.json_utils import convert_objectid_to_str

# Configure logging
logging.basicConfig(level=logging.INFO/////////////,,)
logger = logging.getLogger(__name__)
metrics = RetrieveMetrics()

# Initialize Services
auth_service = AuthService(settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM, settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS)
user_service = UserService(users_collection)

# Default file paths using os.path.join for consistency
DEFAULT_UPLOAD_DIR = "uploaded_files"
DEFAULT_TEST_CASES_CSV_FILE_PATH = os.path.join(DEFAULT_UPLOAD_DIR, "test_cases.csv")
DEFAULT_POSTMAN_OUTPUT_PATH = os.path.join(DEFAULT_UPLOAD_DIR, "postman_collection.json")
# DEFAULT_TEST_DATA_OUTPUT_PATH = os.path.join(DEFAULT_UPLOAD_DIR, "data.json")
DEFAULT_PYTEST_OUTPUT_PATH = os.path.join(DEFAULT_UPLOAD_DIR, "test_api.py")
DEFAULT_CURL_OUTPUT_PATH = os.path.join(DEFAULT_UPLOAD_DIR, "curl_requests.json")
DEFAULT_MOCK_OUTPUT_PATH = os.path.join(DEFAULT_UPLOAD_DIR, "mock_api.py")
BASE_URL = os.getenv("BASE_URL", "/test_ai")

app = FastAPI(
    title="RESTFUL Test AI API",
    description="API for generating test cases, Postman collections and other test artifacts from OpenAPI specifications and feature files.",
    docs_url=f"{BASE_URL}/docs",
    redoc_url=f"{BASE_URL}/redoc",  # ReDoc endpoint (alternative docs, default)
    openapi_tags=[
        {
            "name": "Code Review",
            "description": "Endpoints for different types of code review"
        },
        {
            "name": "Code Assistant",
            "description": "Endpoints for assisting with code generation, comments, docstrings, and explanations"
        }
    ],
    openapi_security=[{
        "oauth2": {
            "type": "oauth2",
            "flow": "password",
            "tokenUrl": f"{BASE_URL}/auth/login"
        }
    }]
)

# Ensure upload directory exists
os.makedirs(DEFAULT_UPLOAD_DIR, exist_ok=True)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*hellooo this is a error func"],  # Specific origins
    allow_credentials=True,
    allow_methods=["*"],  # Allow all methods
    allow_headers=["*"],  # Allow all headers
)

# Touch Route
@app.get(f"{BASE_URL}/touch")
async def touch():
    """
    Endpoint to check if the API is valid and operational.
    """
    return {"message": "API is valid and operational", "status": "success"}

# Auth Routes
@app.post(f"{BASE_URL I have added a dummy func for testinggggg.....ggg..}/auth/register", tags=["Authentication"], summary="Register")
async def register(user: RegisterUser):
    existing_user = await user_service.get_user_by_email(user.email) 
    if (existing_user):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered"
        )
    
    user_id = await user_service.create_user(
        email=user.email,
        full_name=user.full_name,
        password=user.password.get_secret_value(),
        username=user.username,
        company_name=user.company_name,
    )
    return {"message": "User registered successfully", "user_id": user_id}


@app.post(f"{BASE_URL}/auth/login", tags=["Authentication"], summary="Login")
async def login_for_access_token(form_data: EmailAuthPasswordForm = Depends(EmailAuthPasswordForm.as_form)):
    # Get the login identifier (either email or username)
    try:
        login_identifier = form_data.username if form_data.username else form_data.email
        user = await user_service.authenticate_user(login_identifier, form_data.password)
        if not user:
            logger.warning(f"Failed login attempt for user: {login_identifier}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": "Incorrect email or password"
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        
        access_token = auth_service.create_access_token(
            data={"sub": user["email"],"userId": str(user["_id"])}, expires_delta=timedelta(days=settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS)
        )
        return {
            "access_token": access_token, 
            "token_type": "bearer",
            "expiry_time": (datetime.now() + timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S %Z")
        }

    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error during authentication"
        )
     
        
@app.get(f"{BASE_URL}/auth/users/me", tags=["Authentication"], summary="Get current user")
async def read_users_me(current_user: dict = Depends(auth_service.get_current_user)):
    return {
        "id": str(current_user["_id"]),
        "email": current_user["email"],
        "full_name": current_user["full_name"],
        "created_at": current_user["created_at"],
        "updated_at": current_user["updated_at"],
        "active": current_user["active"]
    }
    
# Mount static files with explicit directory creation
app.mount(f"{BASE_URL}/uploaded_files", StaticFiles(directory=DEFAULT_UPLOAD_DIR), name="uploaded_files")

@app.post(f"{BASE_URL}/generate_test_cases_file")
async def generate_test_cases_file(
    current_user: dict = Depends(auth_service.get_current_user),
    code_file: UploadFile = File(...),
    csv_file: UploadFile = File(...),
    output_type: str = Form(...)
):
    """
    Endpoint that accepts:
    1. OpenAPI config file (or code file)
    2. Feature specification CSV file
    3. Output type
    Returns the path of generated test cases file.
    """
    try:
        generator = APITestGenerator()
        # Read the OpenAPI/code file content
        contents = await code_file.read()
        openapi_file_content = contents.decode("utf-8")
        ext = os.path.splitext(code_file.filename)[1].lower()
        
        if ext in ['.py', '.js', '.java']:
            openapi_file_content = generator.convert_code_to_text(openapi_file_content, ext)
            
        # Read the feature CSV file content
        feature_contents = await csv_file.read()
        feature_csv_content = feature_contents.decode("utf-8")
            
        # Save the OpenAPI content for later use
        with open("uploaded_files/last_openapi.json", "w") as f:
            f.write(openapi_file_content)
        
        # Generate test cases using both inputs
        test_cases_csv_str = generator.generate_test_cases(
            openapi_file_content, 
            feature_csv_content,
            DEFAULT_TEST_CASES_CSV_FILE_PATH
        )
        if not test_cases_csv_str and os.path.exists(DEFAULT_TEST_CASES_CSV_FILE_PATH):
            try:
                test_cases_csv_str = generator.load_file(DEFAULT_TEST_CASES_CSV_FILE_PATH)
                logger.info(f"Loaded existing test cases from {DEFAULT_TEST_CASES_CSV_FILE_PATH}")
            except Exception as e:
                logger.error(f"Failed to load existing test cases: {e}")
                raise HTTPException(status_code=500, detail="Failed to load or generate test cases")
        
        if not test_cases_csv_str:
            raise HTTPException(status_code=500, detail="Test case generation failed")
        
        # If output_type is specified, save it for the next endpoint
        if output_type:
            with open("uploaded_files/output_type.txt", "w") as f:
                f.write(output_type)
        
        return {"test_case_file_path": DEFAULT_TEST_CASES_CSV_FILE_PATH}
        
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_URL}/generate_output")
async def generate_output_endpoint(
    current_user: dict = Depends(auth_service.get_current_user),
    output_type: str = Form(None),
    test_cases_file: UploadFile = File(None)
):
    """
    Endpoint 2: Uses previously uploaded OpenAPI file and generates output based on
    specified output type and optional test cases file.
    """
    try:
        generator = APITestGenerator()
        
        # Try to load the saved OpenAPI file
        try:
            with open("uploaded_files/last_openapi.json", "r") as f:
                openapi_file_content = f.read()
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail="Please upload OpenAPI file using generate_test_cases_file endpoint first")
        
        # Try to load saved output_type if not provided
        if not output_type:
            try:
                with open("uploaded_files/output_type.txt", "r") as f:
                    output_type = f.read().strip()
            except FileNotFoundError:
                raise HTTPException(status_code=400, detail="Output type not specified")
        
        # Process test cases file if provided
        if test_cases_file:
            tc_contents = await test_cases_file.read()
            test_cases_csv_str = tc_contents.decode("utf-8")
            # Add this code to save the modified test cases
            with open(DEFAULT_TEST_CASES_CSV_FILE_PATH, "w", encoding="utf-8") as f:
                f.write(test_cases_csv_str)
            logger.info(f"Updated test cases saved to {DEFAULT_TEST_CASES_CSV_FILE_PATH}")
            inserted_id = await save_metrics_to_mongo_from_csv(
                DEFAULT_TEST_CASES_CSV_FILE_PATH,
                current_user
            )
            logger.info(f"Metrics saved to MongoDB (new document _id={inserted_id!r})")

        else:
            # Use existing test cases if available
            test_cases_csv_str = generator.load_file(DEFAULT_TEST_CASES_CSV_FILE_PATH)
            inserted_id = await save_metrics_to_mongo_from_csv(
                DEFAULT_TEST_CASES_CSV_FILE_PATH,
                current_user
            )
            logger.info(f"Metrics saved to MongoDB (new document _id={inserted_id!r})")

        if output_type == "collection":
            # 1) call generator, which now returns Optional[ (postman_json, mock_code) ]
            result = (
                generator.generate_postman_collection(openapi_file_content, test_cases_csv_str)
                if test_cases_csv_str
                else generator.generate_postman_collection(openapi_file_content)
            )
            if not result:
                raise HTTPException(status_code=500, detail="Failed to generate Postman collection")
            postman_json_str, mock_code_str = result

            # 2) save the Postman collection
            if not generator.save_json(postman_json_str, DEFAULT_POSTMAN_OUTPUT_PATH):
                raise HTTPException(status_code=500, detail="Failed to save Postman collection")

           # 3) only try to save mock_api.py if we actually got one
            if mock_code_str:
                with open(DEFAULT_MOCK_OUTPUT_PATH, "w", encoding="utf-8") as f:
                    f.write(mock_code_str)

            # 4) return both file‑paths
            return {
                "output_file_path": DEFAULT_POSTMAN_OUTPUT_PATH,
            **({"mock_api_path": DEFAULT_MOCK_OUTPUT_PATH} if mock_code_str else {})            
            }

        elif output_type == "python":
            # 1) call generator, which now returns Optional[ (python_code, mock_code) ]
            result = (
                generator.generate_pytest_code(openapi_file_content, test_cases_csv_str)
                if test_cases_csv_str
                else generator.generate_pytest_code(openapi_file_content)
            )
            if not result:
                raise HTTPException(status_code=500, detail="Failed to generate Pytest code")
            python_code_str, mock_code_str = result

            # 2) save the Pytest collection
            if python_code_str:
                with open(DEFAULT_PYTEST_OUTPUT_PATH, "w", encoding="utf-8") as f:
                    f.write(python_code_str)
                    
           # 3) only try to save mock_api.py if we actually got one
            if mock_code_str:
                with open(DEFAULT_MOCK_OUTPUT_PATH, "w", encoding="utf-8") as f:
                    f.write(mock_code_str)

            # 4) return both file‑paths
            return {
                "output_file_path": DEFAULT_PYTEST_OUTPUT_PATH,
            **({"mock_api_path": DEFAULT_MOCK_OUTPUT_PATH} if mock_code_str else {})            
            }

        elif output_type == "curl":
            # Generate curl requests.
            # 1) call generator, which now returns Optional[ (curl_json, mock_code) ]
            result = (
                generator.generate_curl_requests(openapi_file_content, test_cases_csv_str)
                if test_cases_csv_str
                else generator.generate_curl_requests(openapi_file_content)
            )
            if not result:
                raise HTTPException(status_code=500, detail="Failed to generate Curl commands")
            curl_json, mock_code_str = result

            # 2) save the Curl commands
            if not generator.save_json(curl_json, DEFAULT_CURL_OUTPUT_PATH):
                raise HTTPException(status_code=500, detail="Failed to save Curl commands")

           # 3) only try to save mock_api.py if we actually got one
            if mock_code_str:
                with open(DEFAULT_MOCK_OUTPUT_PATH, "w", encoding="utf-8") as f:
                    f.write(mock_code_str)

            # 4) return both file‑paths
            return {
                "output_file_path": DEFAULT_CURL_OUTPUT_PATH,
            **({"mock_api_path": DEFAULT_MOCK_OUTPUT_PATH} if mock_code_str else {})            
            }

        else:
            raise HTTPException(status_code=400, detail="Invalid output type specified. Use 'collection', 'python', or 'curl'.")

    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post(f"{BASE_URL}/modify_test_file")
async def modify_test_file_endpoint(
    current_user: dict = Depends(auth_service.get_current_user),
    modification_text: str = Form(...),
    test_file: UploadFile = File(...)
):
    """
    Endpoint that accepts:
    1. Text describing desired modifications
    2. The test file to modify
    Returns the modified file content.
    """
    try:
        generator = APITestGenerator()
        
        # Try to load saved output_type
        try:
            with open("uploaded_files/output_type.txt", "r") as f:
                file_type = f.read().strip()
        except FileNotFoundError:
            raise HTTPException(status_code=400, detail="Output type not found. Please generate test cases first.")
        
        # Determine output file path based on saved type
        if file_type == "collection":
            output_path = DEFAULT_POSTMAN_OUTPUT_PATH
        elif file_type == "python":
            output_path = DEFAULT_PYTEST_OUTPUT_PATH
        elif file_type == "curl":
            output_path = DEFAULT_CURL_OUTPUT_PATH
        else:
            raise HTTPException(status_code=400, detail="Invalid output type found")
            
        # Save uploaded file temporarily
        file_content = await test_file.read()
        with open(output_path, "wb") as f:
            f.write(file_content)
            
        # Modify the file
        modified_content = generator.modify_test_file(
            output_path,
            modification_text,
            file_type
        )
        
        if not modified_content:
            raise HTTPException(status_code=500, detail="Failed to modify test file")
            
        return {"output_file_path": output_path}
        
    except Exception as e:
        logger.error(f"An unexpected error occurred: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get(f"{BASE_URL}/metrics", tags=["Metrics"])
async def test_metrics(
    current_user: dict = Depends(auth_service.get_current_user),
    start_date: Optional[str] = Query(None, description="Start date in YYYY-MM-DD format"), 
    end_date: Optional[str] = Query(None, description="End date in YYYY-MM-DD format"),
    user_id: Optional[str] = Query(None, description="User ID to filter metrics"),
    time_unit: str = Query("day", description="Time unit: day, week, or month") 
):
    try:
        results = {}
        
        # Get test case generation metrics
        test_cases_metrics = await metrics.testcases_gen(start_date, end_date, user_id, time_unit)
        results["test_cases_metrics"] = test_cases_metrics
        
        # Get HTTP methods count metrics
        http_methods_metrics = await metrics.http_methods_count(start_date, end_date, user_id, time_unit)
        results["http_methods_metrics"] = http_methods_metrics
        
        # Get project-user mapping
        project_mapping = await metrics.get_project_user_mapping()
        
        # Convert ObjectIds to strings in project mapping
        results["project_user_mapping"] = convert_objectid_to_str(project_mapping)
        
        # Convert any remaining ObjectIds to strings in the entire results dict
        results = convert_objectid_to_str(results)
        
        return {"metrics": results}
        
    except Exception as e:
         
        logger.error(f"Error retrieving metrics: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Error retrieving metrics: {str(e)}"
        )

if __name__ == "__main__":
    # Set SSL context to allow self-signed certificates
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.check_hostname = False
    ssl_context.verify_mode = ssl.CERT_NONE

    # Run the FastAPI app with SSL enabled
    uvicorn.run("app, host=//////////////////////////////////////////////////)

def print_random_message():
    """
    Prints a random message for demonstration purposes.
    """
    import random
    messages = [
        "Hello, world!",
        "FastAPI is awesome!",
        "This is a random message.",
        "Keep coding and have fun!",
        "API server is running smoothly."
    ]
    print(random.choice(messages))