#!/usr/bin/env python3
"""
Test script for uploading analysis files to Google Drive as Google Docs.

Supports two authentication methods:
1. Service Account - for Shared Drives (Team Drives)
2. OAuth2 - for personal My Drive folders

Requirements:
    pip install google-api-python-client google-auth google-auth-oauthlib

Usage:
    python gdrive_upload_test.py              # Uses service account (for Shared Drives)
    python gdrive_upload_test.py --oauth      # Uses OAuth2 (for personal Drive)
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseUpload
import io

# Configuration
SERVICE_ACCOUNT_FILE = Path(__file__).parent.parent / "fe-dev-sandbox-17634e09f43b.json"
OAUTH_CREDENTIALS_FILE = Path(__file__).parent.parent / "oauth_credentials.json"
OAUTH_TOKEN_FILE = Path.home() / ".config" / "whisperx" / "gdrive_token.json"
TARGET_FOLDER_ID = "0APWmokcmy78jUk9PVA"
OBS_RECORDINGS_DIR = Path.home() / "OBSRecordings"

# Scopes required for Drive API
# Using full drive scope for Shared Drives support
SCOPES = ['https://www.googleapis.com/auth/drive']


def get_service_account_credentials():
    """Get credentials from service account file."""
    return service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE,
        scopes=SCOPES
    )


def get_oauth_credentials():
    """Get or refresh OAuth2 credentials with user consent flow."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    
    creds = None
    
    # Load existing token if available
    if OAUTH_TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(OAUTH_TOKEN_FILE), SCOPES)
    
    # Refresh or get new credentials
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing OAuth token...")
            creds.refresh(Request())
        else:
            if not OAUTH_CREDENTIALS_FILE.exists():
                print(f"\nERROR: OAuth credentials file not found: {OAUTH_CREDENTIALS_FILE}")
                print("\nTo set up OAuth2:")
                print("1. Go to Google Cloud Console -> APIs & Services -> Credentials")
                print("2. Create OAuth 2.0 Client ID (Desktop app)")
                print("3. Download JSON and save as: oauth_credentials.json")
                return None
            
            print("\nStarting OAuth authorization flow...")
            print("A browser window will open for you to authorize access.")
            flow = InstalledAppFlow.from_client_secrets_file(
                str(OAUTH_CREDENTIALS_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)
        
        # Save credentials for next run
        OAUTH_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(OAUTH_TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
        print(f"Token saved to: {OAUTH_TOKEN_FILE}")
    
    return creds


def get_drive_service(use_oauth: bool = False):
    """Create and return an authenticated Drive service."""
    if use_oauth:
        credentials = get_oauth_credentials()
        if not credentials:
            return None
    else:
        credentials = get_service_account_credentials()
    
    return build('drive', 'v3', credentials=credentials)


def parse_analysis_metadata(file_path: Path) -> dict:
    """
    Parse metadata from the analysis file header.
    
    Returns dict with: title, call_type, analyzed_date
    """
    metadata = {
        'title': None,
        'call_type': None,
        'analyzed_date': None,
        'raw_date': None
    }
    
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            # Read first 20 lines to find metadata
            for i, line in enumerate(f):
                if i > 20:
                    break
                
                # Parse **Title:** value
                if line.startswith('**Title:**'):
                    metadata['title'] = line.split('**Title:**')[1].strip()
                
                # Parse **Call Type:** value  
                elif line.startswith('**Call Type:**'):
                    metadata['call_type'] = line.split('**Call Type:**')[1].strip()
                
                # Parse **Analyzed:** value (format: 2026-01-29 23:09:06)
                elif line.startswith('**Analyzed:**'):
                    date_str = line.split('**Analyzed:**')[1].strip()
                    metadata['raw_date'] = date_str
                    try:
                        dt = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                        metadata['analyzed_date'] = dt.strftime('%y_%m_%d')
                    except ValueError:
                        # Try alternate format
                        try:
                            dt = datetime.strptime(date_str.split()[0], '%Y-%m-%d')
                            metadata['analyzed_date'] = dt.strftime('%y_%m_%d')
                        except ValueError:
                            pass
    except Exception as e:
        print(f"Warning: Could not parse metadata: {e}")
    
    return metadata


def load_metadata_json(analysis_file: Path) -> dict:
    """
    Try to load metadata from the companion JSON file.
    """
    # Analysis files are in the recording folder, look for *_metadata.json
    folder = analysis_file.parent
    metadata_files = list(folder.glob('*_metadata.json'))
    
    if metadata_files:
        try:
            with open(metadata_files[0], 'r') as f:
                return json.load(f)
        except Exception:
            pass
    
    return {}


def generate_doc_name(analysis_file: Path) -> str:
    """
    Generate Google Doc name from analysis metadata.
    
    Format: <Call Type> <yy_mm_dd> - <title>
    Example: Interview: AE (SA Peer) 26_01_29 - Selase_Dzobo
    """
    # Parse metadata from the analysis file
    file_metadata = parse_analysis_metadata(analysis_file)
    
    # Also try to load JSON metadata for additional info
    json_metadata = load_metadata_json(analysis_file)
    
    # Get call type (prefer from analysis file, fall back to JSON)
    call_type = file_metadata.get('call_type')
    if not call_type:
        call_type = json_metadata.get('call_type_name', 'Analysis')
    
    # Get date
    date_str = file_metadata.get('analyzed_date')
    if not date_str:
        # Fall back to today's date
        date_str = datetime.now().strftime('%y_%m_%d')
    
    # Get title (person name, interviewee name, or meeting title)
    title = file_metadata.get('title')
    if not title:
        title = json_metadata.get('person_name') or json_metadata.get('meeting_title', 'Untitled')
    
    # Clean up title (replace underscores with spaces for readability)
    title = title.replace('_', ' ')
    
    return f"{call_type} {date_str} - {title}"


def list_accessible_drives(service) -> list:
    """List all Shared Drives the service account can access."""
    try:
        results = service.drives().list(pageSize=10).execute()
        return results.get('drives', [])
    except Exception as e:
        print(f"Error listing drives: {e}")
        return []


def check_folder_info(service, folder_id: str) -> dict:
    """Get information about the target folder or Shared Drive."""
    # First, try to get it as a Shared Drive
    try:
        drive = service.drives().get(driveId=folder_id).execute()
        return {
            'id': drive.get('id'),
            'name': drive.get('name'),
            'driveId': drive.get('id'),
            'is_shared_drive_root': True
        }
    except Exception:
        pass
    
    # Try as a regular folder
    try:
        folder = service.files().get(
            fileId=folder_id,
            fields='id, name, driveId, mimeType',
            supportsAllDrives=True
        ).execute()
        folder['is_shared_drive_root'] = False
        return folder
    except Exception as e:
        return {'error': str(e)}


def find_most_recent_analysis() -> Path | None:
    """Find the most recent analysis file in OBSRecordings."""
    analysis_files = list(OBS_RECORDINGS_DIR.rglob("analysis*.md"))
    if not analysis_files:
        return None
    return max(analysis_files, key=lambda p: p.stat().st_mtime)


def upload_file(service, file_path: Path, folder_id: str, folder_info: dict = None) -> dict:
    """
    Upload a file to Google Drive as a raw file (not converted).
    
    Args:
        service: Authenticated Drive service
        file_path: Path to the file to upload
        folder_id: ID of the target folder or Shared Drive
        folder_info: Folder info dict from check_folder_info()
    
    Returns:
        File metadata dict from the API response
    """
    file_metadata = {
        'name': file_path.name,
        'parents': [folder_id]
    }
    
    media = MediaFileUpload(
        str(file_path),
        mimetype='text/markdown',
        resumable=True
    )
    
    # Check if this is a Shared Drive
    is_shared_drive = folder_info and (
        folder_info.get('is_shared_drive_root') or 
        folder_info.get('driveId') is not None
    )
    
    # Build API parameters
    create_params = {
        'body': file_metadata,
        'media_body': media,
        'fields': 'id, name, webViewLink'
    }
    
    if is_shared_drive:
        create_params['supportsAllDrives'] = True
    
    file = service.files().create(**create_params).execute()
    return file


def markdown_to_html(md_content: str) -> str:
    """
    Convert markdown content to HTML for Google Docs import.
    
    Google Docs handles HTML import much better than raw markdown,
    preserving headings, bold, italic, lists, code blocks, etc.
    """
    import markdown
    
    # Configure markdown with useful extensions
    md = markdown.Markdown(extensions=[
        'tables',           # Support for tables
        'fenced_code',      # ```code blocks```
        'nl2br',            # Convert newlines to <br>
        'sane_lists',       # Better list handling
    ])
    
    html_content = md.convert(md_content)
    
    # Wrap in basic HTML structure with some styling hints
    html_doc = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    body {{ font-family: Arial, sans-serif; line-height: 1.6; }}
    h1, h2, h3 {{ color: #333; }}
    code {{ background-color: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
    pre {{ background-color: #f4f4f4; padding: 12px; border-radius: 5px; overflow-x: auto; }}
    blockquote {{ border-left: 4px solid #ddd; margin-left: 0; padding-left: 16px; color: #666; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background-color: #f4f4f4; }}
</style>
</head>
<body>
{html_content}
</body>
</html>"""
    
    return html_doc


def upload_as_google_doc(service, file_path: Path, folder_id: str, folder_info: dict = None) -> dict:
    """
    Upload a markdown file as a formatted Google Doc.
    
    The markdown is converted to HTML first, which Google Docs imports
    with proper formatting (headings, bold, lists, tables, etc.).
    
    Args:
        service: Authenticated Drive service
        file_path: Path to the markdown file
        folder_id: ID of the target folder or Shared Drive
        folder_info: Folder info dict from check_folder_info()
    
    Returns:
        File metadata dict from the API response
    """
    # Generate document name from metadata
    doc_name = generate_doc_name(file_path)
    
    # Read and convert markdown to HTML
    with open(file_path, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    html_content = markdown_to_html(md_content)
    
    # File metadata - specify Google Docs mimeType for conversion
    file_metadata = {
        'name': doc_name,
        'parents': [folder_id],
        'mimeType': 'application/vnd.google-apps.document'
    }
    
    # Upload as HTML, Drive will convert to Google Docs with formatting
    media = MediaIoBaseUpload(
        io.BytesIO(html_content.encode('utf-8')),
        mimetype='text/html',
        resumable=True
    )
    
    # Check if this is a Shared Drive
    is_shared_drive = folder_info and (
        folder_info.get('is_shared_drive_root') or 
        folder_info.get('driveId') is not None
    )
    
    # Build API parameters
    create_params = {
        'body': file_metadata,
        'media_body': media,
        'fields': 'id, name, webViewLink'
    }
    
    if is_shared_drive:
        create_params['supportsAllDrives'] = True
    
    file = service.files().create(**create_params).execute()
    return file


def main():
    parser = argparse.ArgumentParser(description='Upload analysis files to Google Drive')
    parser.add_argument('--oauth', action='store_true', 
                        help='Use OAuth2 instead of service account')
    parser.add_argument('--file', type=str, help='Specific file to upload (default: most recent)')
    parser.add_argument('--raw', action='store_true',
                        help='Upload as raw markdown file instead of Google Doc')
    args = parser.parse_args()
    
    print("=" * 60)
    print("Google Drive Upload Test")
    print("=" * 60)
    
    auth_method = "OAuth2" if args.oauth else "Service Account"
    print(f"Authentication method: {auth_method}")
    
    if not args.oauth:
        if not SERVICE_ACCOUNT_FILE.exists():
            print(f"ERROR: Service account file not found: {SERVICE_ACCOUNT_FILE}")
            return False
        print(f"Service account: {SERVICE_ACCOUNT_FILE.name}")
    
    # Find analysis file
    if args.file:
        analysis_file = Path(args.file)
        if not analysis_file.exists():
            print(f"ERROR: File not found: {analysis_file}")
            return False
    else:
        print(f"\nSearching for analysis files in: {OBS_RECORDINGS_DIR}")
        analysis_file = find_most_recent_analysis()
        
        if not analysis_file:
            print("ERROR: No analysis files found!")
            return False
    
    print(f"Source file: {analysis_file}")
    print(f"File size: {analysis_file.stat().st_size:,} bytes")
    
    # Show what the document will be named
    if not args.raw:
        doc_name = generate_doc_name(analysis_file)
        print(f"Document name: {doc_name}")
    
    # Authenticate
    print(f"\nTarget folder ID: {TARGET_FOLDER_ID}")
    print("Authenticating with Google Drive...")
    
    try:
        service = get_drive_service(use_oauth=args.oauth)
        if not service:
            return False
        print("Authentication successful!")
        
        # List accessible Shared Drives for debugging
        print("\nListing accessible Shared Drives...")
        drives = list_accessible_drives(service)
        if drives:
            for d in drives:
                print(f"  - {d.get('name')} (ID: {d.get('id')})")
        else:
            print("  No Shared Drives accessible (permissions may still be propagating)")
        
        # Check if target folder is in a Shared Drive
        print("\nChecking target folder/drive...")
        folder_info = check_folder_info(service, TARGET_FOLDER_ID)
        
        if 'error' in folder_info:
            print(f"Warning: Could not get folder info: {folder_info['error']}")
            folder_info = None
        else:
            print(f"  Name: {folder_info.get('name', 'Unknown')}")
            if folder_info.get('is_shared_drive_root'):
                print(f"  Type: Shared Drive root")
            elif folder_info.get('driveId'):
                print(f"  Type: Folder in Shared Drive (ID: {folder_info.get('driveId')})")
            else:
                print("  Type: My Drive folder")
        
        # Upload
        if args.raw:
            print(f"\nUploading as raw file: {analysis_file.name}")
            result = upload_file(service, analysis_file, TARGET_FOLDER_ID, folder_info)
        else:
            print(f"\nCreating Google Doc...")
            result = upload_as_google_doc(service, analysis_file, TARGET_FOLDER_ID, folder_info)
        
        print("\n" + "=" * 60)
        print("Upload successful!")
        print(f"  File ID: {result.get('id')}")
        print(f"  Name: {result.get('name')}")
        print(f"  Link: {result.get('webViewLink')}")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\nERROR: Upload failed: {e}")
        
        # Provide helpful guidance based on error
        error_str = str(e)
        if 'storageQuotaExceeded' in error_str:
            print("\n" + "-" * 60)
            print("This error occurs because service accounts have no storage quota")
            print("for regular My Drive folders.")
            print("\nSolutions:")
            print("  1. Use a Shared Drive (Team Drive) instead")
            print("  2. Run with --oauth flag to use your personal credentials:")
            print(f"     python {Path(__file__).name} --oauth")
            print("-" * 60)
        
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
