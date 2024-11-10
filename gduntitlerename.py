from __future__ import print_function
import os.path
import re
import sys
import logging
import time

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# Configure logging to include debug messages and output to both console and file
logging.basicConfig(
    level=logging.DEBUG,  # Set to DEBUG to capture all levels of logs
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("manage_google_docs.log"),  # Log to file
        logging.StreamHandler()  # Also log to console
    ]
)

# Define the path to your credentials.json file
CREDENTIALS_PATH = '/Users/joebanks/Downloads/credentials.json'

# If modifying these SCOPES, delete the file token.json.
SCOPES = [
    'https://www.googleapis.com/auth/drive',
    'https://www.googleapis.com/auth/documents'
]

def authenticate():
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

def list_google_docs(drive_service):
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

def is_untitled(title):
    """Determine if a document is untitled."""
    # Adjust this regex based on how your untitled documents are named
    return re.match(r'^Untitled(?: document)?$', title, re.IGNORECASE) is not None

def get_first_line(docs_service, doc_id, char_limit=100):
    """Retrieve the first line of the document with comprehensive element handling."""
    try:
        document = docs_service.documents().get(documentId=doc_id).execute()
        content = document.get('body').get('content')
        
        logging.info("Fetching content for document ID: %s", doc_id)
        
        for element_index, element in enumerate(content):
            if 'paragraph' in element:
                paragraph = element.get('paragraph')
                elements = paragraph.get('elements')
                logging.debug("Processing paragraph %d with %d elements.", element_index, len(elements))
                
                for elem_index, elem in enumerate(elements):
                    text_run = elem.get('textRun')
                    if text_run and 'content' in text_run:
                        text = text_run.get('content').strip()
                        logging.debug("Paragraph %d, Element %d: '%s'", element_index, elem_index, text)
                        if text:
                            # Limit the title to the first line or character limit
                            first_line = text.split('\n')[0][:char_limit]
                            logging.info("First non-empty text found: '%s'", first_line)
                            return first_line
            elif 'table' in element:
                table = element.get('table')
                rows = table.get('tableRows', [])
                if rows:
                    for row_index, row in enumerate(rows):
                        cells = row.get('tableCells', [])
                        for cell_index, cell in enumerate(cells):
                            cell_content = cell.get('content', [])
                            for cell_element in cell_content:
                                if 'paragraph' in cell_element:
                                    cell_paragraph = cell_element.get('paragraph')
                                    cell_elements = cell_paragraph.get('elements', [])
                                    for cell_elem in cell_elements:
                                        cell_text_run = cell_elem.get('textRun')
                                        if cell_text_run and 'content' in cell_text_run:
                                            cell_text = cell_text_run.get('content').strip()
                                            logging.debug("Table Row %d, Cell %d, Element: '%s'", row_index, cell_index, cell_text)
                                            if cell_text:
                                                # Limit the title to the first line or character limit
                                                first_line = cell_text.split('\n')[0][:char_limit]
                                                logging.info("First non-empty text found in table: '%s'", first_line)
                                                return first_line
            elif 'sectionBreak' in element:
                logging.debug("Skipping section break at index %d.", element_index)
                continue
            else:
                logging.debug("Skipping non-paragraph/table element at index %d.", element_index)
        
        logging.warning("No non-empty text found in document ID: %s.", doc_id)
        return None
    except HttpError as error:
        logging.error('An error occurred while fetching document %s: %s', doc_id, error)
        return None
    except Exception as e:
        logging.error('Unexpected error while fetching document %s: %s', doc_id, e)
        return None

def validate_title(title, max_length=100):
    """Validate and sanitize the extracted title."""
    if not title:
        return False
    # Example validation: Title should not exceed max_length and should not contain prohibited characters
    if len(title) > max_length:
        title = title[:max_length]
        logging.warning("Title truncated to %d characters: '%s'", max_length, title)
    # Add more validation rules as needed
    # For example, remove any characters not allowed in filenames
    title = re.sub(r'[\\/*?:"<>|]', '', title)
    return title

def update_document_title(drive_service, doc_id, new_title):
    """Update the title of the document."""
    try:
        drive_service.files().update(
            fileId=doc_id,
            body={'name': new_title}
        ).execute()
        logging.info("Updated document %s title to: '%s'", doc_id, new_title)
    except HttpError as error:
        logging.error('An error occurred while updating document %s: %s', doc_id, error)
    except Exception as e:
        logging.error('Unexpected error while updating document %s: %s', doc_id, e)

def trash_document(drive_service, doc_id):
    """Move the document to trash."""
    try:
        drive_service.files().update(
            fileId=doc_id,
            body={'trashed': True}
        ).execute()
        logging.info("Trashed document %s.", doc_id)
    except HttpError as error:
        logging.error('An error occurred while trashing document %s: %s', doc_id, error)
    except Exception as e:
        logging.error('Unexpected error while trashing document %s: %s', doc_id, e)

def main():
    drive_service, docs_service = authenticate()
    docs = list_google_docs(drive_service)
    
    if not docs:
        logging.info('No Google Docs found.')
        return
    
    for doc in docs:
        doc_id = doc.get('id')
        title = doc.get('name')
        if is_untitled(title):
            logging.info("Processing document ID: %s with title: '%s'", doc_id, title)
            try:
                first_line = get_first_line(docs_service, doc_id)
                if first_line:
                    validated_title = validate_title(first_line)
                    if validated_title:
                        update_document_title(drive_service, doc_id, validated_title)
                    else:
                        logging.warning("Validated title is invalid for document %s. Trashing document.", doc_id)
                        trash_document(drive_service, doc_id)
                else:
                    # If no content is found, move the document to trash
                    trash_document(drive_service, doc_id)
            except Exception as e:
                logging.error("Unhandled exception while processing document %s: %s", doc_id, e)
            finally:
                # Optional: Introduce a short delay to prevent hitting rate limits
                time.sleep(0.1)  # Sleep for 100 milliseconds
        else:
            logging.info("Skipping document ID: %s with title: '%s'", doc_id, title)

if __name__ == '__main__':
    main()

