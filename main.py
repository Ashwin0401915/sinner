from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import httpx
import os
from openai import OpenAI, AsyncOpenAI
from fastapi.middleware.cors import CORSMiddleware
from dotenv import load_dotenv
import re

load_dotenv()
app = FastAPI()

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Get environment variables
GITLAB_TOKEN = os.getenv("GITLAB_TOKEN")
if not GITLAB_TOKEN:
    raise ValueError("GITLAB_TOKEN environment variable is not set")

# Configure headers for GitLab API
HEADERS = {"PRIVATE-TOKEN": GITLAB_TOKEN}

# Initialize OpenAI clients - both sync and async
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
async_client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

class MRRequest(BaseModel):
    project_id: int
    source_branch: str
    target_branch: str
    new_branch_name: str
    mr_title: str
    mr_description: str = ""

class ExistingMRRequest(BaseModel):
    project_id: int
    mr_iid: int

class ReviewRequest(BaseModel):
    project_path: str
    merge_request_iid: str

async def create_branch_if_not_exists(project_id, branch_name, ref_branch):
    async with httpx.AsyncClient() as client_http:
        # Check branch existence
        resp = await client_http.get(
            f"https://gitlab.com/api/v4/projects/{project_id}/repository/branches/{branch_name}",
            headers=HEADERS,
        )
        if resp.status_code == 404:
            # Branch does not exist, create it
            create_resp = await client_http.post(
                f"https://gitlab.com/api/v4/projects/{project_id}/repository/branches",
                headers=HEADERS,
                json={"branch": branch_name, "ref": ref_branch},
            )
            if create_resp.status_code not in (200, 201):
                raise Exception(f"Branch creation failed: {create_resp.text}")
        elif resp.status_code != 200:
            raise Exception(f"Error checking branch: {resp.text}")

async def create_merge_request(project_id, source_branch, target_branch, title, description):
    async with httpx.AsyncClient() as client_http:
        mr_resp = await client_http.post(
            f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests",
            headers=HEADERS,
            json={
                "source_branch": source_branch,
                "target_branch": target_branch,
                "title": title,
                "description": description,
            },
        )
        if mr_resp.status_code not in (200, 201):
            raise Exception(f"MR creation failed: {mr_resp.text}")
        return mr_resp.json()

async def get_mr_changes(project_id, mr_iid):
    async with httpx.AsyncClient() as client_http:
        diff_resp = await client_http.get(
            f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}/changes",
            headers=HEADERS,
        )
        if diff_resp.status_code != 200:
            raise Exception(f"Failed to fetch MR changes: {diff_resp.text}")
        return diff_resp.json().get("changes", [])

async def post_mr_comment(project_id, mr_iid, comment):
    async with httpx.AsyncClient() as client_http:
        comment_resp = await client_http.post(
            f"https://gitlab.com/api/v4/projects/{project_id}/merge_requests/{mr_iid}/notes",
            headers=HEADERS,
            json={"body": comment},
        )
        if comment_resp.status_code not in (200, 201):
            raise Exception(f"Failed to post comment: {comment_resp.text}")
        return comment_resp.json()

def extract_changed_code_with_context(diff_text: str) -> dict:
    """
    Extract changed code with minimal context and categorize by type of change.
    Returns a dictionary with added, modified, and removed code sections.
    """
    # Initialize result structure
    result = {
        "added_lines": [],
        "removed_lines": [],
        "modified_blocks": []
    }

    # Skip diff metadata lines
    lines = [line for line in diff_text.split('\n') 
             if not (line.startswith('+++') or line.startswith('---') or line.startswith('@@'))]

    # Process the diff to identify blocks of changes
    current_block = []
    in_change_block = False

    for line in lines:
        if line.startswith('+') and not line.startswith('+++'):
            result["added_lines"].append(line[1:])  # Store without the + prefix
            current_block.append(line)
            in_change_block = True
        elif line.startswith('-') and not line.startswith('---'):
            result["removed_lines"].append(line[1:])  # Store without the - prefix
            current_block.append(line)
            in_change_block = True
        else:
            # This is a context line
            if in_change_block:
                # Add a limited amount of context (1-2 lines) after a change block
                if len(current_block) > 0:
                    current_block.append(line)
                    result["modified_blocks"].append("\n".join(current_block))
                    current_block = []
                    in_change_block = False

    # Handle any remaining block
    if current_block:
        result["modified_blocks"].append("\n".join(current_block))

    return result

def analyze_file_type(file_path: str) -> str:
    """Determine the type of file based on extension or path."""
    if not file_path:
        return "unknown"

    # Extract file extension
    extension = file_path.split('.')[-1].lower() if '.' in file_path else ""

    # Categorize by file type
    if extension in ['py', 'pyw']:
        return "python"
    elif extension in ['js', 'jsx', 'ts', 'tsx']:
        return "javascript"
    elif extension in ['java']:
        return "java"
    elif extension in ['c', 'cpp', 'h', 'hpp']:
        return "c/c++"
    elif extension in ['go']:
        return "golang"
    elif extension in ['rb']:
        return "ruby"
    elif extension in ['php']:
        return "php"
    elif extension in ['html', 'htm']:
        return "html"
    elif extension in ['css', 'scss', 'sass', 'less']:
        return "css"
    elif extension in ['json']:
        return "json"
    elif extension in ['yml', 'yaml']:
        return "yaml"
    elif extension in ['md', 'markdown']:
        return "markdown"
    elif extension in ['sql']:
        return "sql"
    elif extension in ['sh', 'bash']:
        return "shell"
    elif extension in ['dockerfile'] or file_path.lower() == 'dockerfile':
        return "dockerfile"
    elif file_path.lower() == 'makefile':
        return "makefile"
    elif '.gitignore' in file_path.lower():
        return "gitignore"
    else:
        return "other"

def extract_line_numbers_from_diff(diff_text: str) -> dict:
    """Extract line numbers from diff chunks."""
    line_mapping = {}
    current_file = None
    line_number = 0

    # Regular expression to extract line numbers from diff headers
    header_pattern = re.compile(r'@@ -(\d+),\d+ \+(\d+),\d+ @@')

    for line in diff_text.split('\n'):
        if line.startswith('+++'):
            current_file = line[4:].strip()
            continue
            
        # Extract line numbers from diff headers
        header_match = header_pattern.match(line)
        if header_match:
            line_number = int(header_match.group(2))  # Use the new file line number
            continue
            
        if line.startswith('+') and not line.startswith('+++'):
            # This is an added line
            line_mapping[line[1:]] = line_number
            line_number += 1
        elif not line.startswith('-'):
            # This is a context line
            line_number += 1

    return line_mapping

async def generate_code_review(diff_text: str, file_path: str = None) -> str:
    """
    Generate a focused code review that specifically addresses changed code,
    performance impacts, and potential improvements.
    """
    if not diff_text.strip():
        return "No code changes to review."

    # Extract and categorize changed code
    changes = extract_changed_code_with_context(diff_text)

    # Determine file type for language-specific analysis
    file_type = analyze_file_type(file_path) if file_path else "unknown"

    system_prompt = f"""
You are a senior software engineer with expertise in {file_type}.

Your job is to review ONLY the changed code (Git diff) and provide feedback in simple, professional, plain-text format.

REVIEW FORMAT RULES:

1. Start each issue with: Issue 1:, Issue 2:, etc.
2. Include the affected line number(s) in square brackets after the issue number
3. Use **plain text only** – no markdown, no symbols, no formatting
4. Each issue must have:
   - A short one-line title
   - A "Problem:" explanation
   - A "Fix:" recommendation
5. Leave a **blank line** between each issue

DO:
- Only comment on code that has changed
- Use clear, concise, professional language

DO NOT:
- Use markdown (no *, #, -, etc.)
- Add summaries, headings, emojis, or extra sections
- Merge all issues into a paragraph
"""

    user_prompt = f"""
Here is the Git diff for the file: {file_path or 'Unknown File'}

{diff_text}

Please follow this strict format:

Issue 1: [Line X-Y] Short issue title  
Problem: One-sentence explanation of the problem  
Fix: One-sentence clear fix suggestion

Issue 2: [Line A] Another issue  
Problem: ...  
Fix: ...

Do NOT return markdown, emojis, lists, headers, or summaries. Just plain text. One issue per block, with a blank line between.
"""

    try:
        # Use the async client
        response = await async_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1500,
            temperature=0.0,  # Lower temperature for more focused, precise reviews
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error generating review: {str(e)}"

async def generate_structured_code_review(diff_text: str, file_path: str = None) -> str:
    """
    Generate a focused code review that specifically addresses changed code,
    performance impacts, and potential improvements.
    """
    if not diff_text.strip():
        return "No code changes to review."

    # Extract and categorize changed code
    changes = extract_changed_code_with_context(diff_text)

    # Determine file type for language-specific analysis
    file_type = analyze_file_type(file_path) if file_path else "unknown"

    system_prompt = f"""
You are a senior software engineer with expertise in {file_type}.

Your job is to review ONLY the changed code (Git diff) and provide feedback in simple, professional, plain-text format.

REVIEW FORMAT RULES:

1. Start each issue with: Issue 1:, Issue 2:, etc.
2. Include the affected line number(s) in square brackets after the issue number
3. Use **plain text only** – no markdown, no symbols, no formatting
4. Each issue must have:
   - A short one-line title
   - A "Problem:" explanation
   - A "Fix:" recommendation
5. Leave a **blank line** between each issue

DO:
- Only comment on code that has changed
- Use clear, concise, professional language

DO NOT:
- Use markdown (no *, #, -, etc.)
- Add summaries, headings, emojis, or extra sections
- Merge all issues into a paragraph
"""

    user_prompt = f"""
Here is the Git diff for the file: {file_path or 'Unknown File'}

{diff_text}

Please follow this strict format:

Issue 1: [Line X-Y] Short issue title  
Problem: One-sentence explanation of the problem  
Fix: One-sentence clear fix suggestion

Issue 2: [Line A] Another issue  
Problem: ...  
Fix: ...

Do NOT return markdown, emojis, lists, headers, or summaries. Just plain text. One issue per block, with a blank line between.
"""

    try:
        # Use the async client
        response = await async_client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1500,
            temperature=0.0,  # Lower temperature for more focused, precise reviews
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error generating review: {str(e)}"


@app.post("/create-and-review")
async def create_branch_and_mr(data: MRRequest):
    try:
        # Step 1: Create new branch from source branch if it doesn't exist
        await create_branch_if_not_exists(
            data.project_id,
            data.new_branch_name,
            data.source_branch,
        )

        # Step 2: Create MR from new branch to target branch
        mr = await create_merge_request(
            data.project_id,
            data.new_branch_name,
            data.target_branch,
            data.mr_title,
            data.mr_description,
        )

        mr_iid = mr["iid"]

        # Step 3: Fetch changes (diff) from MR
        changes = await get_mr_changes(data.project_id, mr_iid)
        if not changes:
            return {"message": "No changes detected in MR."}

        # Step 4: Generate structured review comments for each file diff
        reviews = []
        for change in changes:
            diff_text = change.get("diff", "")
            file_path = change.get("new_path") or change.get("old_path")
            if diff_text.strip():
                review = await generate_structured_code_review(diff_text, file_path)
                reviews.append(f"## {file_path}\n\n{review}")

        review_comment = "# 🤖 Structured AI Code Review\n\n" + "\n\n".join(reviews)

        # Step 5: Post the review comment on the MR
        await post_mr_comment(data.project_id, mr_iid, review_comment)

        return {
            "message": "Merge Request created and structured AI review posted successfully.",
            "merge_request_url": mr["web_url"],
            "ai_review": review_comment,
        }

    except Exception as e:
        # Add more detailed error logging
        import traceback
        print(f"Error in create_branch_and_mr: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/review-existing")
async def review_existing_mr(data: ExistingMRRequest):
    try:
        # Step 1: Fetch changes from the existing MR
        changes = await get_mr_changes(data.project_id, data.mr_iid)
        if not changes:
            return {"message": "No changes detected in MR."}

        # Step 2: Generate structured review comments for each file diff
        reviews = []
        for change in changes:
            diff_text = change.get("diff", "")
            file_path = change.get("new_path") or change.get("old_path")
            if diff_text.strip():
                review = await generate_structured_code_review(diff_text, file_path)
                reviews.append(f"## {file_path}\n\n{review}")

        review_comment = "# 🤖 Structured AI Code Review\n\n" + "\n\n".join(reviews)

        # Step 3: Post the review comment on the MR
        comment_result = await post_mr_comment(data.project_id, data.mr_iid, review_comment)

        return {
            "message": "Structured AI review posted successfully on existing merge request.",
            "mr_iid": data.mr_iid,
            "ai_review": review_comment,
        }

    except Exception as e:
        # Add more detailed error logging
        import traceback
        print(f"Error in review_existing_mr: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/review")
async def review_mr(data: ReviewRequest):
    try:
        # Extract project ID from project path
        encoded_project_path = data.project_path.replace("/", "%2F")

        async with httpx.AsyncClient() as client_http:
            # Get project ID from path
            project_resp = await client_http.get(
                f"https://gitlab.com/api/v4/projects/{encoded_project_path}",
                headers=HEADERS
            )
            
            if project_resp.status_code != 200:
                print(f"Error getting project: {project_resp.text}")
                raise HTTPException(status_code=400, detail="Failed to get project information")
            
            project_id = project_resp.json().get("id")
            if not project_id:
                raise HTTPException(status_code=400, detail="Project ID not found in response")

            # Step 1: Fetch changes from the existing MR
            changes = await get_mr_changes(project_id, data.merge_request_iid)
            if not changes:
                return {"message": "No changes detected in MR."}

            # Step 2: Generate structured review comments for each file diff
            file_reviews = {}
            reviews = []
            for change in changes:
                diff_text = change.get("diff", "")
                file_path = change.get("new_path") or change.get("old_path")
                if diff_text.strip():
                    try:
                        review = await generate_structured_code_review(diff_text, file_path)
                        file_reviews[file_path] = {"content": review}
                        reviews.append(f"## {file_path}\n\n{review}")
                    except Exception as e:
                        print(f"Error reviewing {file_path}: {str(e)}")
                        file_reviews[file_path] = {"error": str(e)}

            # Combine all reviews into a single formatted review (but don't post it)
            combined_review = ""
            if reviews:
                combined_review = "# 🤖 Structured AI Code Review\n\n" + "\n\n".join(reviews)
            
            return {
                "message": "Structured AI review generated successfully.",
                "mr_iid": data.merge_request_iid,
                "file_reviews": file_reviews,
                "combined_review": combined_review
            }

    except Exception as e:
        # Add more detailed error logging
        import traceback
        print(f"Error in review_mr: {str(e)}")
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=str(e))