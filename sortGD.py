import os
import re
import sys
import logging
import time
from typing import Optional, List, Dict

from openai import OpenAI

from dotenv import load_dotenv  # Optional: For loading environment variables from a .env file

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Optional: Load environment variables from a .env file
# Uncomment the following two lines if you're using a .env file
# load_dotenv()
# os.environ['OPENAI_API_KEY'] = os.getenv('OPENAI_API_KEY')

# Configure logging to include debug messages and output to both console and file
logging.basicConfig(
    level=logging.INFO,  # Change to DEBUG for more detailed logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("manage_google_docs.log"),
        logging.StreamHandler()
    ]
)

# Define the path to your credentials.json file
CREDENTIALS_PATH = '/Users/joebanks/Downloads/credentials.json'

# Define the OpenAI API Key securely
OPENAI_API_KEY = ''

if not OPENAI_API_KEY:
    logging.error("OpenAI API key not found. Please set the OPENAI_API_KEY environment variable.")
    sys.exit(1)

# Initialize OpenAI API
client = OpenAI(api_key=OPENAI_API_KEY)

# Define the categories and their corresponding folder names
CATEGORIES = {
    "Poetry": "Poetry",
    # Add more categories as needed
}

# If modifying these SCOPES, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents'
]

def authenticate() -> (object, object):
    """Authenticate the user and return the service objects for Drive and Docs APIs."""
    creds = None
    # The file token.json stores the user's access and refresh tokens.
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
        logging.info("Loaded credentials from 'token.json'.")
    # If there are no valid credentials, let the user log in.
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logging.info("Token refreshed successfully.")
            except Exception as e:
                logging.error("Failed to refresh token: %s", e)
                creds = None
        if not creds:
            if not os.path.exists(CREDENTIALS_PATH):
                logging.error("Error: '%s' not found.", CREDENTIALS_PATH)
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            creds = flow.run_local_server(port=0)
            logging.info("New credentials obtained.")
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
            logging.info("Credentials saved to 'token.json'.")

    try:
        # Build the service objects
        drive_service = build('drive', 'v3', credentials=creds)
        docs_service = build('docs', 'v1', credentials=creds)
        logging.info("Service objects created successfully.")
        return drive_service, docs_service
    except Exception as e:
        logging.error("Failed to create service objects: %s", e)
        sys.exit(1)

def list_google_docs(drive_service) -> List[Dict]:
    """List all Google Docs in the user's Drive, handling pagination to include all documents."""
    try:
        query = "mimeType='application/vnd.google-apps.document'"
        page_token = None
        docs = []

        while True:
            response = drive_service.files().list(
                q=query,
                spaces='drive',
                fields='nextPageToken, files(id, name)',
                pageToken=page_token,
                pageSize=1000  # Maximum allowed page size
            ).execute()

            files = response.get('files', [])
            docs.extend(files)
            logging.debug("Fetched %d documents in current page.", len(files))

            page_token = response.get('nextPageToken', None)
            if page_token is None:
                break  # No more pages to fetch

        logging.info("Total Google Docs retrieved: %d", len(docs))
        return docs
    except HttpError as error:
        logging.error('An error occurred while listing documents: %s', error)
        return []
    except Exception as e:
        logging.error('Unexpected error: %s', e)
        return []

def is_meaningful(title: str) -> bool:
    """Determine if a document title is meaningful."""
    # Define criteria for meaningful titles
    # Example: Titles longer than 5 characters and not generic
    return len(title.strip()) > 5 and not re.match(r'^Untitled(?: document)?$', title, re.IGNORECASE)

def categorize_document(title: str) -> Optional[str]:
    """Use OpenAI's API to categorize the document based on its title."""
    try:
        response = client.chat.completions.create(model="gpt-3.5-turbo",  # You can choose a different model if desired
        messages=[
            {"role": "system", "content": "You are an assistant that categorizes document titles into predefined categories."},
            {"role": "user", "content": f"Title: {title}\n\nCategory:"},
        ],
        temperature=0.3,
        max_tokens=10,
        n=1)

        category = response.choices[0].message.content.strip()
        logging.info("OpenAI categorization result for '%s': '%s'", title, category)

        # Validate if the category is one of the predefined ones
        if category in CATEGORIES:
            return category
        else:
            logging.warning("Received unknown category '%s' for title '%s'. Assigning to 'Other'.", category, title)
            return "Other"
    except Exception as e:
        logging.error("Error during OpenAI categorization for title '%s': %s", title, e)
        return "Other"  # Default to 'Other' in case of error

def get_or_create_folder(drive_service, folder_name: str, parent_id: Optional[str] = None) -> Optional[str]:
    """Retrieve the folder ID by name or create it if it doesn't exist."""
    try:
        query = f"mimeType='application/vnd.google-apps.folder' and name='{folder_name}'"
        if parent_id:
            query += f" and '{parent_id}' in parents"

        results = drive_service.files().list(
            q=query,
            spaces='drive',
            fields='files(id, name)',
            pageSize=10
        ).execute()

        folders = results.get('files', [])
        if folders:
            folder_id = folders[0].get('id')
            logging.info("Found existing folder '%s' with ID: %s", folder_name, folder_id)
            return folder_id
        else:
            # Create the folder
            file_metadata = {
                'name': folder_name,
                'mimeType': 'application/vnd.google-apps.folder'
            }
            if parent_id:
                file_metadata['parents'] = [parent_id]

            folder = drive_service.files().create(body=file_metadata, fields='id').execute()
            folder_id = folder.get('id')
            logging.info("Created new folder '%s' with ID: %s", folder_name, folder_id)
            return folder_id
    except HttpError as error:
        logging.error("An error occurred while accessing/creating folder '%s': %s", folder_name, error)
        return None
    except Exception as e:
        logging.error("Unexpected error while accessing/creating folder '%s': %s", folder_name, e)
        return None

def move_document_to_folder(drive_service, doc_id: str, folder_id: str):
    """Move the document to the specified folder."""
    try:
        # Retrieve the existing parents to remove
        file = drive_service.files().get(fileId=doc_id, fields='parents').execute()
        previous_parents = ",".join(file.get('parents'))

        # Move the file to the new folder
        drive_service.files().update(
            fileId=doc_id,
            addParents=folder_id,
            removeParents=previous_parents,
            fields='id, parents'
        ).execute()

        logging.info("Moved document ID: %s to folder ID: %s.", doc_id, folder_id)
    except HttpError as error:
        logging.error("An error occurred while moving document %s: %s", doc_id, error)
    except Exception as e:
        logging.error("Unexpected error while moving document %s: %s", doc_id, e)

def main():
    drive_service, docs_service = authenticate()
    docs = list_google_docs(drive_service)

    if not docs:
        logging.info('No Google Docs found.')
        return

    # Pre-fetch or create target folders
    folder_ids = {}
    for category, folder_name in CATEGORIES.items():
        folder_id = get_or_create_folder(drive_service, folder_name)
        if folder_id:
            folder_ids[category] = folder_id
        else:
            logging.error("Failed to access or create folder for category '%s'. Documents in this category will not be moved.", category)

    # Ensure 'Other' folder exists
    if "Other" not in folder_ids:
        other_folder_id = get_or_create_folder(drive_service, "Other")
        if other_folder_id:
            folder_ids["Other"] = other_folder_id
        else:
            logging.error("Failed to access or create 'Other' folder. Documents categorized as 'Other' will not be moved.")

    for doc in docs:
        doc_id = doc.get('id')
        title = doc.get('name')

        logging.info("Processing document ID: %s with title: '%s'", doc_id, title)

        try:
            # Categorize the document using OpenAI based solely on its title
            category = categorize_document(title)
            if not category:
                category = "Other"

            # Get the folder ID for the category, defaulting to 'Other' if necessary
            folder_id = folder_ids.get(category, folder_ids.get("Other"))
            if folder_id:
                # Move the document to the appropriate folder
                move_document_to_folder(drive_service, doc_id, folder_id)
            else:
                logging.warning("No folder found for category '%s'. Assigning to 'Other'.", category)
                other_folder_id = folder_ids.get("Other")
                if other_folder_id:
                    move_document_to_folder(drive_service, doc_id, other_folder_id)
                else:
                    logging.error("No 'Other' folder available to move document %s.", doc_id)
        except Exception as e:
            logging.error("Unhandled exception while processing document %s: %s", doc_id, e)
        finally:
            # Optional: Introduce a short delay to prevent hitting rate limits
            time.sleep(0.1)  # Sleep for 100 milliseconds

if __name__ == '__main__':
    main()
