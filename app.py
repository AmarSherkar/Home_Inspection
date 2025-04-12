import streamlit as st
from logic import HomeInspector
import os
from pathlib import Path
import tempfile
import json
from io import BytesIO
import base64

# Page config
st.set_page_config(
    page_title="Home Inspection AI",
    page_icon="🏠",
    layout="wide"
)

def create_word_download_link(report_data):
    """Generate a download link for the Word report"""
    # Create a temporary file
    temp_dir = tempfile.mkdtemp()
    output_path = os.path.join(temp_dir, "inspection_report.docx")
    
    # Generate the Word report
    inspector = st.session_state.inspector
    inspector.generate_word_report(report_data, output_path)
    
    # Read the file and create download link
    with open(output_path, "rb") as f:
        bytes_data = f.read()
    
    # Create download button
    return bytes_data

# Sidebar for API key input
with st.sidebar:
    st.title("Configuration")
    api_key = st.text_input("Enter Gemini API Key", type="password")
    standards_dir = st.text_input("Path to Building Standards", value="building_standards")
    examples_dir = st.text_input("Path to Examples", value="examples")
    
    if st.button("Initialize Inspector"):
        if not api_key:
            st.error("Please enter a valid Gemini API key")
        else:
            try:
                inspector = HomeInspector(api_key, standards_dir, examples_dir)
                st.session_state.inspector = inspector
                st.session_state.video_processed = False
                st.session_state.report_ready = False
                st.success("Inspector initialized successfully!")
            except Exception as e:
                st.error(f"Error initializing inspector: {str(e)}")

# Main app
st.title("🏠 AI Home Inspection System")
st.markdown("Upload a video of your home for a detailed inspection report")

if 'inspector' not in st.session_state:
    st.warning("Please initialize the inspector in the sidebar first")
    st.stop()

inspector = st.session_state.inspector

# File upload
uploaded_file = st.file_uploader(
    "Upload a video of your home", 
    type=["mp4", "mov", "avi"]
)

if uploaded_file is not None and not st.session_state.get("video_processed", False):
    with st.spinner("Processing video..."):
        # Save uploaded file to temp location
        temp_dir = tempfile.mkdtemp()
        video_path = os.path.join(temp_dir, uploaded_file.name)
        
        with open(video_path, "wb") as f:
            f.write(uploaded_file.getbuffer())
        
        # Process video and extract frames
        try:
            frame_paths = inspector.process_video(video_path)
            inspector.upload_user_media([video_path] + list(frame_paths.values()))
            
            st.session_state.video_processed = True
            st.session_state.frame_paths = frame_paths
            st.session_state.video_path = video_path
            
            st.success("Video processed successfully!")
            st.write(f"Extracted {len(frame_paths)} frames from video")
            
            # Show sample frames
            cols = st.columns(3)
            for i, (name, path) in enumerate(frame_paths.items()):
                if i < 3:  # Show first 3 frames
                    cols[i].image(path, caption=f"Frame at {name.replace('video_', '').replace('s', 's')}")
                        
        except Exception as e:
            st.error(f"Error processing video: {str(e)}")

# Generate Report
if st.session_state.get("video_processed", False) and not st.session_state.get("report_ready", False):
    if st.button("Generate Inspection Report"):
        with st.spinner("Generating report (this may take a few minutes)..."):
            try:
                report = inspector.generate_report()
                st.session_state.report = report
                
                # Save report to JSON file
                with open("inspection_report.json", "w") as f:
                    json.dump(report, f, indent=4)
                    
                st.session_state.report_ready = True
                st.success("Report generated successfully!")
            except Exception as e:
                st.error(f"Error generating report: {str(e)}")

# Display report if available
if st.session_state.get("report_ready", False):
    report = st.session_state.report
    
    st.header("Inspection Report")
    
    # Executive Summary
    with st.expander("Executive Summary", expanded=True):
        st.subheader("Overall Condition")
        st.write(report['executiveSummary']['overallCondition'])
        
        st.subheader("Critical Issues")
        for issue in report['executiveSummary']['criticalIssues']:
            st.error(f"⚠️ {issue}")
            
        st.subheader("Recommended Actions")
        for action in report['executiveSummary']['recommendedActions']:
            st.info(f"🔧 {action}")
    
    # Detailed Inspection
    st.header("Detailed Inspection Findings")
    for finding in report['detailedInspection']:
        with st.expander(f"{finding['area']} - {finding['condition']}", expanded=False):
            cols = st.columns([1, 3])
            
            # Show image if available
            if finding.get('mediaReference'):
                media_ref = finding['mediaReference']
                if media_ref.startswith('frame_'):
                    frame_path = os.path.join("extracted_frames", media_ref)
                    if os.path.exists(frame_path):
                        cols[0].image(frame_path, caption=f"Frame at {finding.get('timestamp', 'N/A')}")
            
            # Show details
            with cols[1]:
                st.markdown(f"**Compliance Status:** `{finding['complianceStatus']}`")
                
                if finding.get('issuesFound'):
                    st.markdown("**Issues Found:**")
                    for issue in finding['issuesFound']:
                        st.markdown(f"- {issue}")
                
                if finding.get('referenceDoc') and finding.get('referenceSection'):
                    st.markdown(f"**Standard Reference:** {finding['referenceDoc']} - {finding['referenceSection']}")
                
                if finding.get('recommendation'):
                    st.markdown(f"**Recommendation:** {finding['recommendation']}")
    
    # Maintenance Notes
    with st.expander("Maintenance Schedule", expanded=False):
        for schedule in report['maintenanceNotes']['maintenanceSchedule']:
            st.subheader(f"{schedule['frequency']} Tasks")
            for task in schedule['tasks']:
                st.markdown(f"- {task}")
        
        if report['maintenanceNotes'].get('costConsiderations'):
            st.subheader("Cost Considerations")
            for cost in report['maintenanceNotes']['costConsiderations']:
                st.markdown(f"- {cost}")
    
    # Download buttons
    st.subheader("Download Reports")
    col1, col2 = st.columns(2)
    
    with col1:
        st.download_button(
            label="Download JSON Report",
            data=json.dumps(report, indent=4),
            file_name="home_inspection_report.json",
            mime="application/json"
        )
    
    with col2:
        word_bytes = create_word_download_link(report)
        st.download_button(
            label="Download Word Report",
            data=word_bytes,
            file_name="home_inspection_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        )

    # Reset button
    if st.button("Start New Inspection"):
        st.session_state.video_processed = False
        st.session_state.report_ready = False
        st.session_state.report = None
        st.session_state.frame_paths = None
        st.rerun()  # This is the corrected line
