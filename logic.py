import os
import json
import time
import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
import datetime
from pathlib import Path
from google.generativeai import caching
import cv2
from typing import Dict, List
import tempfile

class HomeInspector:
    def __init__(self, api_key: str, standards_dir: str, examples_dir: str):
        self.api_key = api_key
        self.standards_dir = Path(standards_dir)
        self.examples_dir = Path(examples_dir)
        self.document_dict = {
            'building_standards': {},
            'examples': {'example1': {}, 'example2': {}},
            'user_data': {}
        }
        self.SUPPORTED_EXTENSIONS = {'.txt', '.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png'}
        self._initialize_model()

    def _initialize_model(self):
        genai.configure(api_key=self.api_key)
        
        # Load building standards
        self._load_standards()
        
        # Load examples
        self._load_examples()
        
        # Initialize model with cache
        self.cache = caching.CachedContent.create(
            model='models/gemini-1.5-flash-002',
            display_name='home_inspection_cache',
            system_instruction=(
                'You are an expert at analysing residential building and producing detailed inspection reports.'
                'Your job is to analyse the user provided media and produce a detailed inspection report based on the reference standards you have access to.'
            ),
            contents=[doc for doc in self.document_dict['building_standards'].values()],
            ttl=datetime.timedelta(minutes=60),
        )
        
        generation_config = {
            "temperature": 0.1,
            "max_output_tokens": 8192,
            "response_mime_type": "application/json",
        }
        
        self.model = genai.GenerativeModel.from_cached_content(
            cached_content=self.cache, 
            generation_config=generation_config
        )

    def _load_standards(self):
        for file_path in self.standards_dir.rglob('*'):
            if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                try:
                    uploaded_file = genai.upload_file(str(file_path))
                    self.document_dict['building_standards'][file_path.name] = uploaded_file
                except Exception as e:
                    print(f"Error loading standard {file_path.name}: {str(e)}")

    def _load_examples(self):
        for file_path in self.examples_dir.rglob('*'):
            if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                try:
                    subfolder = file_path.parent.name
                    if subfolder in ['example1', 'example2']:
                        uploaded_file = genai.upload_file(str(file_path))
                        self.document_dict['examples'][subfolder][file_path.name] = uploaded_file
                except Exception as e:
                    print(f"Error loading example {file_path.name}: {str(e)}")

    def process_video(self, video_path: str, output_dir: str = "extracted_frames") -> Dict[str, str]:
        """Process video and extract frames at regular intervals"""
        Path(output_dir).mkdir(exist_ok=True)
        frame_paths = {}
        
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {video_path}")
        
        fps = cap.get(cv2.CAP_PROP_FPS)
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        duration = frame_count / fps
        
        # Extract frames every 5 seconds
        for timestamp in range(0, int(duration), 5):
            cap.set(cv2.CAP_PROP_POS_MSEC, timestamp * 1000)
            ret, frame = cap.read()
            if ret:
                frame_filename = f"frame_{timestamp}.jpg"
                frame_path = str(Path(output_dir) / frame_filename)
                cv2.imwrite(frame_path, frame)
                frame_paths[f"video_{timestamp}s"] = frame_path
        
        cap.release()
        return frame_paths

    def upload_user_media(self, media_paths: List[str]):
        """Upload user media files to Gemini"""
        for path in media_paths:
            file_path = Path(path)
            if file_path.suffix.lower() in self.SUPPORTED_EXTENSIONS:
                try:
                    uploaded_file = genai.upload_file(str(file_path))
                    self.document_dict['user_data'][file_path.name] = uploaded_file
                except Exception as e:
                    print(f"Error loading user media {file_path.name}: {str(e)}")
            elif file_path.suffix.lower() in {'.mp4', '.mov', '.avi'}:
                self._upload_video(str(file_path))

    def _upload_video(self, video_path: str):
        """Upload video file to Gemini"""
        print("Uploading video file...")
        video_file = genai.upload_file(path=video_path)
        print(f"Completed upload: {video_file.uri}")
        
        while video_file.state.name == "PROCESSING":
            print('Waiting for video to be processed.')
            time.sleep(10)
            video_file = genai.get_file(video_file.name)
        
        if video_file.state.name == "FAILED":
            raise ValueError(video_file.state.name)
        
        print(f'Video processing complete: {video_file.uri}')
        self.document_dict['user_data'][Path(video_path).name] = video_file

    def generate_report(self) -> Dict:
        """Generate inspection report based on uploaded media"""
        prompt =  """
You have been supplied with a set of building standards and manufacturer specifications to evaluate the photos and videos against.
Please be specific about any violations of building codes or manufacturer specifications found in the documentation.

Analyze the uploaded photos and videos of the building and generate a detailed inspection report in JSON format.
Be exhaustive in your inspection and cover all aspects of the building shown in the media.

The response should be a valid JSON object with the following structure:

{
  "detailedInspection": [
    {
      "area": "string",
      "mediaReference": "string",
      "timestamp": "string",
      "condition": "string",
      "complianceStatus": "string",
      "issuesFound": ["string"],
      "referenceDoc": "string",
      "referenceSection": "string",
      "recommendation": "string"
    }
  ],
  "executiveSummary": {
    "overallCondition": "string",
    "criticalIssues": ["string"],
    "recommendedActions": ["string"]
  },
  "maintenanceNotes": {
    "recurringIssues": ["string"],
    "preventiveRecommendations": ["string"],
    "maintenanceSchedule": [
      {
        "frequency": "string",
        "tasks": ["string"]
      }
    ],
    "costConsiderations": ["string"]
  }
}

Ensure the response is a valid JSON object that can be parsed.
"""
        
        content = [{'text': prompt}]
        
        # Add user media
        content.append({'text': 'User provided media:'})
        for name, doc in self.document_dict['user_data'].items():
            content.append({'text': f"User Document: {name}"})
            content.append(doc)
        
        # Start chat session
        chat_session = self.model.start_chat(history=[{"role": "user", "parts": content}])
        
        # Get response
        response = chat_session.send_message(
            "Please generate a detailed building report. "
            "Please provide a detailed answer with elaboration on the report and reference material."
        )
        
        return json.loads(response.text)