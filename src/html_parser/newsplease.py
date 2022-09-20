"""Parser using news-please library: https://github.com/fhamborg/news-please"""

import logging

from newsplease import NewsPlease
import requests

from src.base import HTMLParser, ParserInput, ParserOutput, HTMLTextBlock, HTMLData
from src.config import HTML_MIN_NO_LINES_FOR_VALID_TEXT, HTML_HTTP_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)


class NewsPleaseParser(HTMLParser):
    """HTML parser which uses the news-please library."""

    def __init__(self) -> None:
        super().__init__()

    @property
    def name(self) -> str:
        """Return parser name"""
        return "newsplease"

    def parse_html(self, html: str, input: ParserInput) -> ParserOutput:
        """
        Parse HTML using newsplease.

        :param html: HTML string to parse
        :param url: URL of web page

        :return ParsedHTML: parsed HTML
        """

        try:
            article = NewsPlease.from_html(html=html, url=input.url, fetch_images=False)
        except Exception as e:
            logger.error(f"Failed to parse {input.url} for {input.id}: {e}")
            return self._get_empty_response(input)

        return self._newsplease_article_to_parsed_html(article, input)

    def parse(self, input: ParserInput) -> ParserOutput:
        """
        Parse website using newsplease

        :param url: URL of web page

        :return ParsedHTML: parsed HTML
        """

        try:
            response = requests.get(
                input.url,
                verify=False,
                allow_redirects=True,
                timeout=HTML_HTTP_REQUEST_TIMEOUT,
            )

        except Exception as e:
            logger.error(f"Could not fetch {input.url} for {input.id}: {e}")
            return self._get_empty_response(input)

        return self.parse_html(response.text, input)

    def _newsplease_article_to_parsed_html(
        self, newsplease_article, input: ParserInput
    ) -> ParserOutput:
        """
        Convert a newsplease article to parsed HTML. Returns an empty response if the article contains no text.

        :param newsplease_article: article returned by `NewsPlease.from_url` or `NewsPlease.from_html`
        :param url: URL of web page

        :return ParsedHTML: parsed HTML
        """

        text = newsplease_article.maintext

        if not text:
            return self._get_empty_response(input)

        text_by_line = text.split("\n")
        has_valid_text = len(text_by_line) >= HTML_MIN_NO_LINES_FOR_VALID_TEXT

        text_blocks = [
            HTMLTextBlock.parse_obj(
                {
                    "text_block_id": f"b{idx}",
                    "text": [text],
                }
            )
            for idx, text in enumerate(text_by_line)
        ]

        return ParserOutput(
            id=input.id,
            url=input.url,
            document_name=input.document_name,
            document_description=input.document_description,
            content_type=input.content_type,
            document_slug=input.document_slug,
            html_data=HTMLData(
                detected_title=newsplease_article.title,
                detected_date=newsplease_article.date_publish,  # We also have access to the modified and downloaded dates in the class
                has_valid_text=has_valid_text,
                text_blocks=text_blocks,
            ),
        )
