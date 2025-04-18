#!/usr/bin/env python3
"""
Reporting Module for Malware Detonation Platform
-----------------------------------------------

This module provides reporting functionality for generating
HTML, JSON, and PDF reports from malware analysis results.
"""

import os
import json
import logging
import datetime
from pathlib import Path
from typing import Dict, List, Any, Optional, Union

# Configure logging
logger = logging.getLogger(__name__)

class ReportGenerator:
    """Class for generating reports from malware analysis results."""
    
    def __init__(self, templates_dir: str = '/app/templates/reports', output_dir: str = '/app/data/reports'):
        """
        Initialize the report generator with configuration settings.
        
        Args:
            templates_dir: Directory containing report templates
            output_dir: Directory where reports will be saved
        """
        self.templates_dir = Path(templates_dir)
        self.output_dir = Path(output_dir)
        
        # Ensure directories exist
        os.makedirs(self.templates_dir, exist_ok=True)
        os.makedirs(self.output_dir, exist_ok=True)
        
        logger.info(f"Initialized ReportGenerator with templates_dir={templates_dir}, output_dir={output_dir}")
    
    def generate_sample_report(self, sample_data: Dict[str, Any], report_format: str = 'html') -> Optional[Path]:
        """
        Generate a report for a malware sample.
        
        Args:
            sample_data: Dictionary containing sample information
            report_format: Format of the report (html, json, pdf)
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        # Validate input
        if not sample_data or 'id' not in sample_data or 'sha256' not in sample_data:
            logger.error("Invalid sample data provided")
            return None
        
        # Create report identifier
        report_id = f"sample_{sample_data['id']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Generate report based on format
        if report_format == 'json':
            return self._generate_json_report(report_id, sample_data)
        elif report_format == 'html':
            return self._generate_html_sample_report(report_id, sample_data)
        elif report_format == 'pdf':
            return self._generate_pdf_sample_report(report_id, sample_data)
        else:
            logger.error(f"Unsupported report format: {report_format}")
            return None
    
    def generate_detonation_report(self, job_data: Dict[str, Any], report_format: str = 'html') -> Optional[Path]:
        """
        Generate a report for a detonation job.
        
        Args:
            job_data: Dictionary containing job information and results
            report_format: Format of the report (html, json, pdf)
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        # Validate input
        if not job_data or 'id' not in job_data or 'status' not in job_data:
            logger.error("Invalid job data provided")
            return None
        
        # Create report identifier
        report_id = f"job_{job_data['id']}_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Generate report based on format
        if report_format == 'json':
            return self._generate_json_report(report_id, job_data)
        elif report_format == 'html':
            return self._generate_html_detonation_report(report_id, job_data)
        elif report_format == 'pdf':
            return self._generate_pdf_detonation_report(report_id, job_data)
        else:
            logger.error(f"Unsupported report format: {report_format}")
            return None
    
    def generate_summary_report(self, samples: List[Dict[str, Any]], jobs: List[Dict[str, Any]], 
                              report_format: str = 'html') -> Optional[Path]:
        """
        Generate a summary report covering multiple samples and jobs.
        
        Args:
            samples: List of sample dictionaries
            jobs: List of job dictionaries
            report_format: Format of the report (html, json, pdf)
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        # Validate input
        if not samples and not jobs:
            logger.error("No data provided for summary report")
            return None
        
        # Create report identifier
        report_id = f"summary_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"
        
        # Combine data
        summary_data = {
            "samples": samples,
            "jobs": jobs,
            "generated_at": datetime.datetime.now().isoformat(),
            "sample_count": len(samples),
            "job_count": len(jobs)
        }
        
        # Generate report based on format
        if report_format == 'json':
            return self._generate_json_report(report_id, summary_data)
        elif report_format == 'html':
            return self._generate_html_summary_report(report_id, summary_data)
        elif report_format == 'pdf':
            return self._generate_pdf_summary_report(report_id, summary_data)
        else:
            logger.error(f"Unsupported report format: {report_format}")
            return None
    
    def _generate_json_report(self, report_id: str, data: Dict[str, Any]) -> Optional[Path]:
        """
        Generate a JSON report.
        
        Args:
            report_id: Identifier for the report
            data: Dictionary containing report data
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        try:
            # Add report metadata
            report_data = {
                "report_id": report_id,
                "generated_at": datetime.datetime.now().isoformat(),
                "data": data
            }
            
            # Create output file path
            output_path = self.output_dir / f"{report_id}.json"
            
            # Write JSON file
            with open(output_path, 'w') as f:
                json.dump(report_data, f, indent=2)
            
            logger.info(f"Generated JSON report at {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error generating JSON report: {str(e)}")
            return None
    
    def _generate_html_sample_report(self, report_id: str, sample_data: Dict[str, Any]) -> Optional[Path]:
        """
        Generate an HTML report for a malware sample.
        
        Args:
            report_id: Identifier for the report
            sample_data: Dictionary containing sample information
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        try:
            # Check if HTML template exists
            template_path = self.templates_dir / 'sample_report.html'
            if not template_path.exists():
                # Create basic template if it doesn't exist
                self._create_default_sample_template()
            
            # Read template
            with open(template_path, 'r') as f:
                template_content = f.read()
            
            # Replace placeholders with data
            report_content = template_content
            report_content = report_content.replace('{{REPORT_ID}}', report_id)
            report_content = report_content.replace('{{GENERATED_AT}}', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            report_content = report_content.replace('{{SAMPLE_ID}}', str(sample_data.get('id', 'N/A')))
            report_content = report_content.replace('{{SAMPLE_NAME}}', sample_data.get('name', 'Unknown'))
            report_content = report_content.replace('{{SAMPLE_SHA256}}', sample_data.get('sha256', 'N/A'))
            report_content = report_content.replace('{{SAMPLE_MD5}}', sample_data.get('md5', 'N/A'))
            report_content = report_content.replace('{{SAMPLE_SHA1}}', sample_data.get('sha1', 'N/A'))
            report_content = report_content.replace('{{SAMPLE_TYPE}}', sample_data.get('file_type', 'Unknown'))
            report_content = report_content.replace('{{SAMPLE_SIZE}}', str(sample_data.get('file_size', 'Unknown')))
            report_content = report_content.replace('{{SAMPLE_DESCRIPTION}}', sample_data.get('description', 'No description available'))
            
            # Handle tags
            tags = sample_data.get('tags', '')
            if isinstance(tags, list):
                tags = ', '.join(tags)
            report_content = report_content.replace('{{SAMPLE_TAGS}}', tags)
            
            # Create output file path
            output_path = self.output_dir / f"{report_id}.html"
            
            # Write HTML file
            with open(output_path, 'w') as f:
                f.write(report_content)
            
            logger.info(f"Generated HTML sample report at {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error generating HTML sample report: {str(e)}")
            return None
    
    def _generate_html_detonation_report(self, report_id: str, job_data: Dict[str, Any]) -> Optional[Path]:
        """
        Generate an HTML report for a detonation job.
        
        Args:
            report_id: Identifier for the report
            job_data: Dictionary containing job information and results
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        try:
            # Check if HTML template exists
            template_path = self.templates_dir / 'detonation_report.html'
            if not template_path.exists():
                # Create basic template if it doesn't exist
                self._create_default_detonation_template()
            
            # Read template
            with open(template_path, 'r') as f:
                template_content = f.read()
            
            # Replace placeholders with data
            report_content = template_content
            report_content = report_content.replace('{{REPORT_ID}}', report_id)
            report_content = report_content.replace('{{GENERATED_AT}}', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            report_content = report_content.replace('{{JOB_ID}}', str(job_data.get('id', 'N/A')))
            report_content = report_content.replace('{{JOB_STATUS}}', job_data.get('status', 'Unknown'))
            report_content = report_content.replace('{{VM_TYPE}}', job_data.get('vm_type', 'Unknown'))
            report_content = report_content.replace('{{VM_NAME}}', job_data.get('vm_name', 'N/A'))
            report_content = report_content.replace('{{SAMPLE_ID}}', str(job_data.get('sample_id', 'N/A')))
            report_content = report_content.replace('{{SAMPLE_NAME}}', job_data.get('sample_name', 'Unknown'))
            
            # Handle timestamps
            created_at = job_data.get('created_at', 'Unknown')
            started_at = job_data.get('started_at', 'N/A')
            completed_at = job_data.get('completed_at', 'N/A')
            
            report_content = report_content.replace('{{CREATED_AT}}', str(created_at))
            report_content = report_content.replace('{{STARTED_AT}}', str(started_at))
            report_content = report_content.replace('{{COMPLETED_AT}}', str(completed_at))
            
            # Handle error message
            error_message = job_data.get('error_message', '')
            report_content = report_content.replace('{{ERROR_MESSAGE}}', error_message)
            
            # Process results (if available)
            results_html = '<p>No results available</p>'
            
            # Get results from the job data
            results = []
            if 'results' in job_data and isinstance(job_data['results'], list):
                results = job_data['results']
            
            if results:
                results_html = '<div class="results-container">'
                
                for result in results:
                    result_type = result.get('result_type', 'unknown')
                    result_data = result.get('result_data', {})
                    
                    if isinstance(result_data, str):
                        try:
                            result_data = json.loads(result_data)
                        except json.JSONDecodeError:
                            # Keep as string if not valid JSON
                            pass
                    
                    # Create section based on result type
                    results_html += f'<div class="result-section"><h3>{result_type.title()}</h3>'
                    
                    if isinstance(result_data, dict):
                        results_html += '<table class="result-table"><tbody>'
                        for key, value in result_data.items():
                            # Convert complex values to string representation
                            if isinstance(value, (dict, list)):
                                value = json.dumps(value, indent=2)
                            results_html += f'<tr><th>{key}</th><td>{value}</td></tr>'
                        results_html += '</tbody></table>'
                    elif isinstance(result_data, list):
                        results_html += '<ul class="result-list">'
                        for item in result_data:
                            if isinstance(item, dict):
                                item_str = ', '.join(f"{k}: {v}" for k, v in item.items())
                                results_html += f'<li>{item_str}</li>'
                            else:
                                results_html += f'<li>{item}</li>'
                        results_html += '</ul>'
                    else:
                        results_html += f'<pre>{result_data}</pre>'
                    
                    results_html += '</div>'
                
                results_html += '</div>'
            
            report_content = report_content.replace('{{RESULTS}}', results_html)
            
            # Create output file path
            output_path = self.output_dir / f"{report_id}.html"
            
            # Write HTML file
            with open(output_path, 'w') as f:
                f.write(report_content)
            
            logger.info(f"Generated HTML detonation report at {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error generating HTML detonation report: {str(e)}")
            return None
    
    def _generate_html_summary_report(self, report_id: str, summary_data: Dict[str, Any]) -> Optional[Path]:
        """
        Generate an HTML summary report.
        
        Args:
            report_id: Identifier for the report
            summary_data: Dictionary containing summary information
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        try:
            # Check if HTML template exists
            template_path = self.templates_dir / 'summary_report.html'
            if not template_path.exists():
                # Create basic template if it doesn't exist
                self._create_default_summary_template()
            
            # Read template
            with open(template_path, 'r') as f:
                template_content = f.read()
            
            # Replace placeholders with data
            report_content = template_content
            report_content = report_content.replace('{{REPORT_ID}}', report_id)
            report_content = report_content.replace('{{GENERATED_AT}}', datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            report_content = report_content.replace('{{SAMPLE_COUNT}}', str(summary_data.get('sample_count', 0)))
            report_content = report_content.replace('{{JOB_COUNT}}', str(summary_data.get('job_count', 0)))
            
            # Generate samples table
            samples_html = '<p>No samples available</p>'
            if 'samples' in summary_data and summary_data['samples']:
                samples_html = '<table class="data-table"><thead><tr>'
                samples_html += '<th>ID</th><th>Name</th><th>Type</th><th>SHA256</th><th>Size</th><th>Uploaded</th>'
                samples_html += '</tr></thead><tbody>'
                
                for sample in summary_data['samples']:
                    samples_html += '<tr>'
                    samples_html += f'<td>{sample.get("id", "N/A")}</td>'
                    samples_html += f'<td>{sample.get("name", "Unknown")}</td>'
                    samples_html += f'<td>{sample.get("file_type", "Unknown")}</td>'
                    samples_html += f'<td>{sample.get("sha256", "N/A")[:10]}...</td>'
                    samples_html += f'<td>{sample.get("file_size", "Unknown")}</td>'
                    samples_html += f'<td>{sample.get("created_at", "Unknown")}</td>'
                    samples_html += '</tr>'
                
                samples_html += '</tbody></table>'
            
            report_content = report_content.replace('{{SAMPLES_TABLE}}', samples_html)
            
            # Generate jobs table
            jobs_html = '<p>No jobs available</p>'
            if 'jobs' in summary_data and summary_data['jobs']:
                jobs_html = '<table class="data-table"><thead><tr>'
                jobs_html += '<th>ID</th><th>Sample</th><th>VM Type</th><th>Status</th><th>Created</th><th>Completed</th>'
                jobs_html += '</tr></thead><tbody>'
                
                for job in summary_data['jobs']:
                    jobs_html += '<tr>'
                    jobs_html += f'<td>{job.get("id", "N/A")}</td>'
                    jobs_html += f'<td>{job.get("sample_name", "Unknown")}</td>'
                    jobs_html += f'<td>{job.get("vm_type", "Unknown")}</td>'
                    
                    # Style status based on value
                    status = job.get("status", "Unknown")
                    status_class = ""
                    if status == "completed":
                        status_class = "status-success"
                    elif status == "failed":
                        status_class = "status-error"
                    elif status == "running":
                        status_class = "status-running"
                    
                    jobs_html += f'<td class="{status_class}">{status}</td>'
                    jobs_html += f'<td>{job.get("created_at", "Unknown")}</td>'
                    jobs_html += f'<td>{job.get("completed_at", "N/A")}</td>'
                    jobs_html += '</tr>'
                
                jobs_html += '</tbody></table>'
            
            report_content = report_content.replace('{{JOBS_TABLE}}', jobs_html)
            
            # Create output file path
            output_path = self.output_dir / f"{report_id}.html"
            
            # Write HTML file
            with open(output_path, 'w') as f:
                f.write(report_content)
            
            logger.info(f"Generated HTML summary report at {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error generating HTML summary report: {str(e)}")
            return None
    
    def _generate_pdf_sample_report(self, report_id: str, sample_data: Dict[str, Any]) -> Optional[Path]:
        """
        Generate a PDF report for a malware sample.
        
        Args:
            report_id: Identifier for the report
            sample_data: Dictionary containing sample information
            
        Returns:
            Path to the generated report file, or None if generation failed
        """
        try:
            # First generate HTML report
            html_path = self._generate_html_sample_report(report_id, sample_data)
            if not html_path:
                return None
            
            # Convert HTML to PDF - using a simple placeholder implementation
            # In a real implementation, you would use a library like weasyprint or pdfkit
            logger.warning("PDF generation is not fully implemented - this is a placeholder")
            
            # Create output file path
            output_path = self.output_dir / f"{report_id}.pdf"
            
            # In a real implementation, convert HTML to PDF here
            # For now, just create a dummy PDF file with a message
            with open(output_path, 'w') as f:
                f.write(f"This is a placeholder PDF report for {report_id}. The actual implementation would convert the HTML report to PDF.")
            
            logger.info(f"Generated placeholder PDF sample report at {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error generating PDF sample report: {str(e)}")
            return None
    
    def _generate_pdf_detonation_report(self, report_id: str, job_data: Dict[str, Any]) -> Optional[Path]:
        """Similar to _generate_pdf_sample_report but for detonation jobs"""
        # Implementation would be similar to _generate_pdf_sample_report
        # First generate HTML, then convert to PDF
        return self._placeholder_pdf_report(report_id, "detonation job report")
    
    def _generate_pdf_summary_report(self, report_id: str, summary_data: Dict[str, Any]) -> Optional[Path]:
        """Similar to _generate_pdf_sample_report but for summary reports"""
        # Implementation would be similar to _generate_pdf_sample_report
        # First generate HTML, then convert to PDF
        return self._placeholder_pdf_report(report_id, "summary report")
    
    def _placeholder_pdf_report(self, report_id: str, report_type: str) -> Optional[Path]:
        """Create a placeholder PDF report for unimplemented PDF generation"""
        try:
            # Create output file path
            output_path = self.output_dir / f"{report_id}.pdf"
            
            # Create a dummy PDF file with a message
            with open(output_path, 'w') as f:
                f.write(f"This is a placeholder PDF {report_type} for {report_id}. "
                       f"The actual implementation would convert the HTML report to PDF.")
            
            logger.info(f"Generated placeholder PDF {report_type} at {output_path}")
            return output_path
        except Exception as e:
            logger.error(f"Error generating placeholder PDF report: {str(e)}")
            return None
    
    def _create_default_sample_template(self) -> None:
        """Create a default HTML template for sample reports"""
        template_content = """<!DOCTYPE html>
<html>
<head>
    <title>Malware Sample Report - {{REPORT_ID}}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1, h2 { color: #4a6fa5; }
        .report-header { margin-bottom: 30px; }
        .report-section { margin-bottom: 30px; }
        .report-section h2 { border-bottom: 1px solid #eaeaea; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }
        th { background-color: #f8f9fa; }
        .hash-value { font-family: monospace; word-break: break-all; }
    </style>
</head>
<body>
    <div class="report-header">
        <h1>Malware Sample Report</h1>
        <p>Report ID: {{REPORT_ID}}</p>
        <p>Generated: {{GENERATED_AT}}</p>
    </div>
    
    <div class="report-section">
        <h2>Sample Information</h2>
        <table>
            <tr>
                <th width="30%">ID:</th>
                <td>{{SAMPLE_ID}}</td>
            </tr>
            <tr>
                <th>Name:</th>
                <td>{{SAMPLE_NAME}}</td>
            </tr>
            <tr>
                <th>File Type:</th>
                <td>{{SAMPLE_TYPE}}</td>
            </tr>
            <tr>
                <th>File Size:</th>
                <td>{{SAMPLE_SIZE}} bytes</td>
            </tr>
            <tr>
                <th>SHA256:</th>
                <td class="hash-value">{{SAMPLE_SHA256}}</td>
            </tr>
            <tr>
                <th>MD5:</th>
                <td class="hash-value">{{SAMPLE_MD5}}</td>
            </tr>
            <tr>
                <th>SHA1:</th>
                <td class="hash-value">{{SAMPLE_SHA1}}</td>
            </tr>
            <tr>
                <th>Tags:</th>
                <td>{{SAMPLE_TAGS}}</td>
            </tr>
        </table>
    </div>
    
    <div class="report-section">
        <h2>Description</h2>
        <p>{{SAMPLE_DESCRIPTION}}</p>
    </div>
    
    <div class="report-footer">
        <p><em>This report was generated by the Malware Detonation Platform.</em></p>
    </div>
</body>
</html>"""
        
        template_path = self.templates_dir / 'sample_report.html'
        with open(template_path, 'w') as f:
            f.write(template_content)
        
        logger.info(f"Created default sample report template at {template_path}")
    
    def _create_default_detonation_template(self) -> None:
        """Create a default HTML template for detonation reports"""
        template_content = """<!DOCTYPE html>
<html>
<head>
    <title>Detonation Job Report - {{REPORT_ID}}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1, h2, h3 { color: #4a6fa5; }
        .report-header { margin-bottom: 30px; }
        .report-section { margin-bottom: 30px; }
        .report-section h2 { border-bottom: 1px solid #eaeaea; padding-bottom: 10px; }
        table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
        th, td { text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }
        th { background-color: #f8f9fa; }
        pre { background-color: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; }
        .results-container { margin-top: 20px; }
        .result-section { margin-bottom: 30px; }
        .result-table { margin-bottom: 15px; }
        .result-list { margin-bottom: 15px; }
        .status-success { color: #28a745; }
        .status-error { color: #dc3545; }
        .status-running { color: #007bff; }
    </style>
</head>
<body>
    <div class="report-header">
        <h1>Detonation Job Report</h1>
        <p>Report ID: {{REPORT_ID}}</p>
        <p>Generated: {{GENERATED_AT}}</p>
    </div>
    
    <div class="report-section">
        <h2>Job Information</h2>
        <table>
            <tr>
                <th width="30%">Job ID:</th>
                <td>{{JOB_ID}}</td>
            </tr>
            <tr>
                <th>Status:</th>
                <td class="status-{{JOB_STATUS}}">{{JOB_STATUS}}</td>
            </tr>
            <tr>
                <th>Sample ID:</th>
                <td>{{SAMPLE_ID}}</td>
            </tr>
            <tr>
                <th>Sample Name:</th>
                <td>{{SAMPLE_NAME}}</td>
            </tr>
            <tr>
                <th>VM Type:</th>
                <td>{{VM_TYPE}}</td>
            </tr>
            <tr>
                <th>VM Name:</th>
                <td>{{VM_NAME}}</td>
            </tr>
            <tr>
                <th>Created:</th>
                <td>{{CREATED_AT}}</td>
            </tr>
            <tr>
                <th>Started:</th>
                <td>{{STARTED_AT}}</td>
            </tr>
            <tr>
                <th>Completed:</th>
                <td>{{COMPLETED_AT}}</td>
            </tr>
            {% if ERROR_MESSAGE %}
            <tr>
                <th>Error:</th>
                <td class="status-error">{{ERROR_MESSAGE}}</td>
            </tr>
            {% endif %}
        </table>
    </div>
    
    <div class="report-section">
        <h2>Detonation Results</h2>
        {{RESULTS}}
    </div>
    
    <div class="report-footer">
        <p><em>This report was generated by the Malware Detonation Platform.</em></p>
    </div>
</body>
</html>"""
        
        template_path = self.templates_dir / 'detonation_report.html'
        with open(template_path, 'w') as f:
            f.write(template_content)
        
        logger.info(f"Created default detonation report template at {template_path}")
    
    def _create_default_summary_template(self) -> None:
        """Create a default HTML template for summary reports"""
        template_content = """<!DOCTYPE html>
<html>
<head>
    <title>Summary Report - {{REPORT_ID}}</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; }
        h1, h2 { color: #4a6fa5; }
        .report-header { margin-bottom: 30px; }
        .report-section { margin-bottom: 30px; }
        .report-section h2 { border-bottom: 1px solid #eaeaea; padding-bottom: 10px; }
        .data-table { width: 100%; border-collapse: collapse; margin-bottom: 20px; }
        .data-table th, .data-table td { text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }
        .data-table th { background-color: #f8f9fa; }
        .data-table tr:hover { background-color: #f5f5f5; }
        .status-success { color: #28a745; }
        .status-error { color: #dc3545; }
        .status-running { color: #007bff; }
    </style>
</head>
<body>
    <div class="report-header">
        <h1>Summary Report</h1>
        <p>Report ID: {{REPORT_ID}}</p>
        <p>Generated: {{GENERATED_AT}}</p>
    </div>
    
    <div class="report-section">
        <h2>Overview</h2>
        <table>
            <tr>
                <th width="30%">Total Samples:</th>
                <td>{{SAMPLE_COUNT}}</td>
            </tr>
            <tr>
                <th>Total Detonation Jobs:</th>
                <td>{{JOB_COUNT}}</td>
            </tr>
        </table>
    </div>
    
    <div class="report-section">
        <h2>Malware Samples</h2>
        {{SAMPLES_TABLE}}
    </div>
    
    <div class="report-section">
        <h2>Detonation Jobs</h2>
        {{JOBS_TABLE}}
    </div>
    
    <div class="report-footer">
        <p><em>This report was generated by the Malware Detonation Platform.</em></p>
    </div>
</body>
</html>"""
        
        template_path = self.templates_dir / 'summary_report.html'
        with open(template_path, 'w') as f:
            f.write(template_content)
        
        logger.info(f"Created default summary report template at {template_path}")

# Example usage
if __name__ == "__main__":
    import argparse
    import sys
    
    # Set up argument parser
    parser = argparse.ArgumentParser(description="Generate reports from malware analysis data")
    parser.add_argument("--sample-id", type=int, help="Sample ID to generate report for")
    parser.add_argument("--job-id", type=int, help="Detonation job ID to generate report for")
    parser.add_argument("--summary", action="store_true", help="Generate a summary report")
    parser.add_argument("--format", choices=['html', 'json', 'pdf'], default='html', help="Report format")
    parser.add_argument("--output-dir", default="/app/data/reports", help="Directory to store reports")
    
    # Parse arguments
    args = parser.parse_args()
    
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Create report generator
    generator = ReportGenerator(output_dir=args.output_dir)
    
    # Check if at least one report type is specified
    if not args.sample_id and not args.job_id and not args.summary:
        parser.print_help()
        sys.exit(1)
    
    # Generate requested reports
    if args.sample_id:
        print(f"Generating {args.format} report for sample ID {args.sample_id}...")
        # In a real implementation, you would fetch the sample data from the database
        # For demo purposes, use a dummy sample
        sample_data = {
            "id": args.sample_id,
            "name": "Example Malware Sample",
            "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
            "md5": "d41d8cd98f00b204e9800998ecf8427e",
            "sha1": "da39a3ee5e6b4b0d3255bfef95601890afd80709",
            "file_type": "application/x-dosexec",
            "file_size": 123456,
            "description": "This is an example malware sample for demonstration purposes.",
            "tags": ["example", "demo", "malware"]
        }
        
        report_path = generator.generate_sample_report(sample_data, args.format)
        if report_path:
            print(f"Report generated successfully: {report_path}")
        else:
            print("Failed to generate report")
            sys.exit(1)
    
    if args.job_id:
        print(f"Generating {args.format} report for job ID {args.job_id}...")
        # In a real implementation, you would fetch the job data from the database
        # For demo purposes, use a dummy job
        job_data = {
            "id": args.job_id,
            "sample_id": 123,
            "sample_name": "Example Malware",
            "status": "completed",
            "vm_type": "windows-10-x64",
            "vm_name": "detonation-abc123",
            "created_at": "2023-05-01T12:00:00",
            "started_at": "2023-05-01T12:01:00",
            "completed_at": "2023-05-01T12:10:00",
            "results": [
                {
                    "result_type": "summary",
                    "result_data": {
                        "status": "completed",
                        "detected_behaviors": ["File creation", "Registry modification", "Network connection"]
                    }
                },
                {
                    "result_type": "network",
                    "result_data": [
                        {"protocol": "TCP", "destination": "192.168.1.1", "port": 80}
                    ]
                }
            ]
        }
        
        report_path = generator.generate_detonation_report(job_data, args.format)
        if report_path:
            print(f"Report generated successfully: {report_path}")
        else:
            print("Failed to generate report")
            sys.exit(1)
    
    if args.summary:
        print(f"Generating {args.format} summary report...")
        # In a real implementation, you would fetch the data from the database
        # For demo purposes, use dummy data
        samples = [
            {
                "id": 1,
                "name": "Example Malware 1",
                "file_type": "application/x-dosexec",
                "sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "file_size": 123456,
                "created_at": "2023-05-01"
            },
            {
                "id": 2,
                "name": "Example Malware 2",
                "file_type": "application/pdf",
                "sha256": "6b86b273ff34fce19d6b804eff5a3f5747ada4eaa22f1d49c01e52ddb7875b4b",
                "file_size": 234567,
                "created_at": "2023-05-02"
            }
        ]
        
        jobs = [
            {
                "id": 1,
                "sample_id": 1,
                "sample_name": "Example Malware 1",
                "vm_type": "windows-10-x64",
                "status": "completed",
                "created_at": "2023-05-01",
                "completed_at": "2023-05-01"
            },
            {
                "id": 2,
                "sample_id": 2,
                "sample_name": "Example Malware 2",
                "vm_type": "ubuntu-20-04",
                "status": "failed",
                "created_at": "2023-05-02",
                "completed_at": "2023-05-02"
            }
        ]
        
        report_path = generator.generate_summary_report(samples, jobs, args.format)
        if report_path:
            print(f"Report generated successfully: {report_path}")
        else:
            print("Failed to generate report")
            sys.exit(1)
    
    print("All reports generated successfully")
