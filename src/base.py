"""Base classes for parsing."""

from abc import ABC, abstractmethod
from collections import Counter
from datetime import date
from enum import Enum
from typing import Optional, Sequence, Tuple, List
from typing import Union

import layoutparser.elements as lp_elements
from langdetect import DetectorFactory
from langdetect import detect
from pydantic import BaseModel, AnyHttpUrl, Field, root_validator

from src.config import PIPELINE_RUN, PIPELINE_STAGE
from src.utils import get_logger

logger = get_logger(__name__)


class BlockType(str, Enum):
    """
    List of possible block types from the PubLayNet model.

    https://layout-parser.readthedocs.io/en/latest/notes/modelzoo.html#model-label-map
    """

    TEXT = "Text"
    TITLE = "Title"
    LIST = "List"
    TABLE = "Table"
    FIGURE = "Figure"
    INFERRED = "Inferred from gaps"
    AMBIGUOUS = "Ambiguous"  # TODO: remove this when OCRProcessor._infer_block_type is implemented


class ContentType(str, Enum):
    """List of document content types that can be handled by the parser."""

    HTML = "text/html"
    PDF = "application/pdf"


class TextBlock(BaseModel):
    """
    Base class for a text block.

    :attribute text: list of text lines contained in the text block
    :attribute text_block_id: unique identifier for the text block
    :attribute language: language of the text block. 2-letter ISO code, optional.
    :attribute type: predicted type of the text block
    :attribute type_confidence: confidence score of the text block being of the predicted type
    """

    text: List[str]
    text_block_id: str
    language: Optional[
        str
    ] = None  # TODO: validate this against a list of language ISO codes
    type: BlockType
    type_confidence: float = Field(ge=0, le=1)

    def to_string(self) -> str:
        """Returns the lines in a text block as a string with the lines separated by spaces."""

        return " ".join([line.strip() for line in self.text])


class HTMLTextBlock(TextBlock):
    """
    Text block parsed from an HTML document.

    Type is set to "Text" with a confidence of 1.0 by default, as we do not predict types for text blocks parsed from HTML.
    """

    type: BlockType = BlockType.TEXT
    type_confidence: float = 1.0


class PDFTextBlock(TextBlock):
    """
    Text block parsed from a PDF document.

    Stores the text and positional information for a single text block extracted from a document.

    :attribute coords: list of coordinates of the vertices defining the boundary of the text block.
        Each coordinate is a tuple in the format (x, y). (0, 0) is at the top left corner of
        the page, and the positive x- and y- directions are right and down.
    :attribute page_number: page number of the page containing the text block.
    """

    coords: List[Tuple[float, float]]
    page_number: int = Field(ge=0)

    def to_string(self) -> str:
        """Returns the lines in a text block as a string with the lines separated by spaces."""

        return " ".join([line.strip() for line in self.text])

    @classmethod
    def from_layoutparser(
        cls, text_block: lp_elements.TextBlock, text_block_id: str, page_number: int
    ) -> "PDFTextBlock":
        """
        Create a TextBlock from a LayoutParser TextBlock.

        :param text_block: LayoutParser TextBlock
        :param text_block_id: ID to use for the resulting TextBlock.
        :param page_number: Page number of the text block.
        :raises ValueError: if the LayoutParser TextBlock does not have all of the properties `text`, `coordinates`, `score` and `type`.
        :return TextBlock:
        """

        null_values_of_lp_block = [
            k
            for k, v in {
                "text": text_block.text,
                "coordinates": text_block.coordinates,
                "score": text_block.score,
                "type": text_block.type,
            }.items()
            if v is None
        ]
        if len(null_values_of_lp_block) > 0:
            raise ValueError(
                f"LayoutParser TextBlock has null values: {null_values_of_lp_block}"
            )

        # Convert from a potentially not rectangular quadrilateral to a rectangle.
        # This method does nothing if the text block is already a rectangle.
        text_block = text_block.to_rectangle()

        new_format_coordinates = [
            (text_block.block.x_1, text_block.block.y_1),
            (text_block.block.x_2, text_block.block.y_1),
            (text_block.block.x_2, text_block.block.y_2),
            (text_block.block.x_1, text_block.block.y_2),
        ]

        # Ignoring types below as this method will raise an error if any of these values are None above.
        return PDFTextBlock(
            text=[text_block.text],  # type: ignore
            text_block_id=text_block_id,  # e.g. p0_b3
            coords=new_format_coordinates,  # type: ignore
            type_confidence=text_block.score,  # type: ignore
            type=text_block.type,  # type: ignore
            page_number=page_number,
        )


class ParserInput(BaseModel):
    """Base class for input to a parser."""

    document_id: str
    document_metadata: dict
    document_name: str
    document_description: str
    document_url: Optional[AnyHttpUrl]
    document_content_type: Optional[ContentType]
    document_slug: str

    @root_validator
    def check_content_type_and_url(cls, values) -> None:
        """Either both or neither of content type and url should be null."""
        if (
            values["document_content_type"] is None
            and values["document_url"] is not None
        ) or (
            values["document_content_type"] is not None
            and values["document_url"] is None
        ):
            raise ValueError(
                "Both document_content_type and document_url must be null or not null."
            )

        return values


class HTMLData(BaseModel):
    """Set of metadata specific to HTML documents."""

    detected_title: Optional[str]
    detected_date: Optional[date]
    has_valid_text: bool
    text_blocks: Sequence[HTMLTextBlock]


class PDFPageMetadata(BaseModel):
    """
    Set of metadata for a single page of a PDF document.

    :attribute dimensions: (width, height) of the page in pixels
    """

    page_number: int = Field(ge=0)
    dimensions: Tuple[float, float]


class PDFData(BaseModel):
    """
    Set of metadata unique to PDF documents.

    :attribute pages: List of pages contained in the document
    :attribute filename: Name of the PDF file, without extension
    :attribute md5sum: md5sum of PDF content
    :attribute language: list of 2-letter ISO language codes, optional. If null, the OCR processor didn't support language detection
    """

    page_metadata: Sequence[PDFPageMetadata]
    md5sum: str
    text_blocks: Sequence[PDFTextBlock]


class ParserOutput(BaseModel):
    """Base class for an output to a parser."""

    document_id: str
    document_metadata: dict
    document_name: str
    document_description: str
    document_url: Optional[AnyHttpUrl]
    languages: Optional[Sequence[str]] = None
    translated: bool = False
    document_slug: str  # for better links to the frontend hopefully soon
    document_content_type: Optional[ContentType]
    html_data: Optional[HTMLData] = None
    pdf_data: Optional[PDFData] = None

    @root_validator
    def check_html_pdf_metadata(cls, values):
        """Check that html_data is set if content_type is HTML, or pdf_data is set if content_type is PDF."""
        if (
            values["document_content_type"] == ContentType.HTML
            and values["html_data"] is None
        ):
            raise ValueError("html_metadata must be set for HTML documents")

        if (
            values["document_content_type"] == ContentType.PDF
            and values["pdf_data"] is None
        ):
            raise ValueError("pdf_metadata must be null for HTML documents")

        if values["document_content_type"] is None and (
            values["html_data"] is not None or values["pdf_data"] is not None
        ):
            raise ValueError(
                "html_metadata and pdf_metadata must be null for documents with no content type."
            )

        return values

    @root_validator
    def check_content_type_and_url(cls, values) -> None:
        """Either both or neither of content type and url should be null."""
        if (
            values["document_content_type"] is None
            and values["document_url"] is not None
        ) or (
            values["document_content_type"] is not None
            and values["document_url"] is None
        ):
            raise ValueError(
                "Both document_content_type and document_url must be null or not null."
            )

        return values

    @property
    def text_blocks(self) -> Sequence[TextBlock]:  # type: ignore
        """
        Return the text blocks in the document. These could differ in format depending on the content type.

        :return: Sequence[TextBlock]
        """

        if self.document_content_type == ContentType.HTML:
            return self.html_data.text_blocks  # type: ignore
        elif self.document_content_type == ContentType.PDF:
            return self.pdf_data.text_blocks  # type: ignore

    def to_string(self) -> str:  # type: ignore
        """Return the text blocks in the parser output as a string"""

        return " ".join(
            [text_block.to_string().strip() for text_block in self.text_blocks]
        )

    def detect_and_set_languages(self) -> "ParserOutput":
        """
        Detect language of the text and set the language attribute. Return an instance of ParserOutput with the language attribute set.

        Assumes that a document only has one language.
        """

        if self.document_content_type != ContentType.HTML:
            logger.warning(
                "Language detection should not be required for non-HTML documents, but it has been run on one. This "
                "will overwrite any document languages detected via other means, e.g. OCR. ",
                extra={
                    "props": LogProps.parse_obj(
                        {
                            "pipeline_run": PIPELINE_RUN,
                            "pipeline_stage": PIPELINE_STAGE,
                            "pipeline_stage_subsection": f"{__name__}",
                            "document_in_process": None,
                            "error": None,
                        }
                    ).dict()
                },
            )

        # language detection is not deterministic, so we need to set a seed
        DetectorFactory.seed = 0

        if len(self.text_blocks) > 0:
            detected_language = detect(self.to_string())
            self.languages = [detected_language]
            for text_block in self.text_blocks:
                text_block.language = detected_language

        return self

    def set_document_languages_from_text_blocks(
        self, min_language_proportion: float = 0.4
    ):
        """
        Store the document languages attribute as part of the object by getting all languages with proportion above `min_language_proportion`.

        :attribute min_language_proportion: Minimum proportion of text blocks in a language for it to be considered a language of the document.
        """

        all_text_block_languages = [
            text_block.language for text_block in self.text_blocks
        ]

        if all([lang is None for lang in all_text_block_languages]):
            self.languages = None

        else:
            lang_counter = Counter(
                [lang for lang in all_text_block_languages if lang is not None]
            )
            self.languages = [
                lang
                for lang, count in lang_counter.items()
                if count / len(all_text_block_languages) > min_language_proportion
            ]

        return self


class HTMLParser(ABC):
    """Base class for an HTML parser."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identifier for the parser. Can be used if we want to identify the parser that parsed a web page."""
        raise NotImplementedError()

    @abstractmethod
    def parse_html(self, html: str, url: str) -> ParserOutput:
        """Parse an HTML string directly."""
        raise NotImplementedError()

    @abstractmethod
    def parse(self, input: ParserInput) -> ParserOutput:
        """Parse a web page, by fetching the HTML and then parsing it. Implementations will often call `parse_html`."""
        raise NotImplementedError()

    def _get_empty_response(self, input: ParserInput) -> ParserOutput:
        """Return ParsedHTML object with empty fields."""
        return ParserOutput(
            document_id=input.document_id,
            document_metadata=input.document_metadata,
            document_content_type=input.document_content_type,
            document_name=input.document_name,
            document_description=input.document_description,
            document_url=input.document_url,
            document_slug=input.document_slug,
            html_data=HTMLData(
                text_blocks=[],
                detected_date=None,
                detected_title="",
                has_valid_text=False,
            ),
        )


class ErrorLog(BaseModel):
    """Log format for errors.

    Defined to standardize the error logs such that these can be filtered effectively when the application runs in
    production in AWS.
    """

    status_code: Union[str, None]
    error_message: Union[str, None]


class LogProps(BaseModel):
    """Log format for logs.

    Defined to standardize the logs such that these can be filtered effectively when the application runs in
    production in AWS.
    """

    pipeline_run: str
    pipeline_stage: str
    pipeline_stage_subsection: str
    document_in_process: Union[str, None]
    error: Union[ErrorLog, None]
