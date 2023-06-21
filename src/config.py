import multiprocessing
import os
from typing import List

HTML_MIN_NO_LINES_FOR_VALID_TEXT = int(
    os.getenv("HTML_MIN_NO_LINES_FOR_VALID_TEXT", "6")
)
HTML_HTTP_REQUEST_TIMEOUT = int(os.getenv("HTML_HTTP_REQUEST_TIMEOUT", "30"))  # seconds
HTML_MAX_PARAGRAPH_LENGTH_WORDS = int(
    os.getenv("HTML_MAX_PARAGRAPH_LENGTH_WORDS", "500")
)

TARGET_LANGUAGES: List[str] = (
    os.getenv("TARGET_LANGUAGES", "en").lower().split(",")
)  # comma-separated 2-letter ISO codes


RUN_PDF_PARSER = os.getenv("RUN_PDF_PARSER", "true").lower() == "true"
RUN_HTML_PARSER = os.getenv("RUN_HTML_PARSER", "true").lower() == "true"
RUN_TRANSLATION = os.getenv("RUN_TRANSLATION", "true").lower() == "true"

# Default set by trial and error based on behaviour of the parsing model
PDF_N_PROCESSES = int(os.getenv("PDF_N_PROCESSES", multiprocessing.cpu_count() / 2))
FILES_TO_PARSE = os.getenv("files_to_parse")
LOGGING_LEVEL = os.getenv("LOGGING_LEVEL", "DEBUG").upper()

PROJECT_ID = os.getenv("PROJECT_ID")
PROCESSOR_ID = os.getenv("PROCESSOR_ID")
LOCATION = os.getenv("LOCATION", "eu")
MIME_TYPE = os.getenv("MIME_TYPE", "application/pdf")
BLOCK_OVERLAP_THRESHOLD = float(os.getenv("OVERLAP_THRESHOLD", "0.7"))
LAYOUTPARSER_BOX_DETECTION_THRESHOLD = float(
    os.getenv("LAYOUTPARSER_BOX_DETECTION_THRESHOLD", "0.8")
)
