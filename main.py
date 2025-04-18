import json
import logging
import time

import requests
from bs4 import BeautifulSoup

# Setup logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)


def scrape_hukumonline_tips(max_pages=5):
    """
    Scrapes legal tips articles from HukumOnline Tips section.

    Args:
        max_pages (int): The maximum number of pagination pages to scrape.
                         Set to None to scrape all pages (use with caution).

    Returns:
        list: A list of dictionaries, where each dictionary contains the
              'url', 'title', and cleaned 'content' of an article.
    """
    base_url = "https://www.hukumonline.com"
    start_url = f"{base_url}/klinik/tips/"
    current_url = start_url
    all_articles_content = []
    page_count = 0

    # Use a session object for potential connection reuse and header management
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
        }
    )

    while current_url and (max_pages is None or page_count < max_pages):
        logging.info(f"Scraping page: {current_url}")
        page_count += 1
        try:
            response = session.get(current_url, timeout=20)
            response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        except requests.exceptions.RequestException as e:
            logging.error(f"Error fetching page {current_url}: {e}")
            break  # Stop if a listing page fails

        soup = BeautifulSoup(response.text, "html.parser")

        # --- Find article links on the current listing page ---
        # Based on user-provided HTML, links are within <div class="css-m2i9m0">
        # inside <a> tags with class '__tips_idx_click'
        article_links_container = soup.find("div", class_="css-m2i9m0")
        if not article_links_container:
            logging.warning(
                f"Could not find article links container (div.css-m2i9m0) on {current_url}. Structure might have changed."
            )
            # Attempt to find links directly if container missing
            article_links = soup.find_all(
                "a",
                class_="__tips_idx_click",
                href=lambda href: href and href.startswith("/klinik/a/"),
            )
            if not article_links:
                logging.error("No article links found on page. Stopping.")
                break  # Stop if structure changes significantly
        else:
            article_links = article_links_container.find_all(
                "a",
                class_="__tips_idx_click",
                href=lambda href: href and href.startswith("/klinik/a/"),
            )

        if not article_links:
            logging.warning(
                f"No article links found within the container on {current_url}"
            )

        for link in article_links:
            article_href = link.get("href")
            article_title_tag = link.find("h2", class_="css-1udxi4r")
            article_title = (
                article_title_tag.get_text(strip=True)
                if article_title_tag
                else "No Title Found"
            )

            if article_href:
                article_url = base_url + article_href
                logging.info(f"  Scraping article: {article_url}")
                try:
                    article_response = session.get(article_url, timeout=20)
                    article_response.raise_for_status()
                    article_soup = BeautifulSoup(article_response.text, "html.parser")

                    # --- Extract the main content section ---
                    # Updated content extraction logic to handle current HTML structure
                    question_text, summary_text, main_content_text = (
                        extract_article_content(article_soup, article_url)
                    )

                    # Add to list if content was found
                    if main_content_text:
                        article_data = {
                            "url": article_url,
                            "judul": article_title,
                            "pertanyaan": question_text if question_text else "",
                            "ringkasan": summary_text if summary_text else "",
                            "konten": main_content_text,
                        }
                        all_articles_content.append(article_data)
                    elif question_text and not main_content_text:
                        logging.warning(
                            f"    Extracted question but failed to extract main content for article: {article_url}"
                        )
                    else:
                        logging.error(
                            f"    Failed to extract any content for article: {article_url}"
                        )

                except requests.exceptions.RequestException as e:
                    logging.error(f"    Error fetching article {article_url}: {e}")
                except Exception as e:
                    logging.error(
                        f"    Error parsing article {article_url}: {e}", exc_info=True
                    )  # Log full traceback for parsing errors

                time.sleep(
                    0.75
                )  # Be polite, add a small delay between article requests

        # --- Find the next page link ---
        pagination_ul = soup.find("ul", class_="css-1gd80ut")
        next_page_link_url = None
        if pagination_ul:
            # Find the 'Next Page' link specifically by looking for the 'rel="next"' attribute or the SVG icon structure
            next_page_tag = pagination_ul.find(
                "a", rel="next", class_="__pagination_next_click"
            )
            if next_page_tag and next_page_tag.get("href"):
                next_page_href = next_page_tag["href"]
                # Ensure it's a relative path starting correctly
                if next_page_href.startswith("/klinik/tips/page/"):
                    next_page_link_url = base_url + next_page_href
                else:
                    logging.warning(
                        f"Found next page link with unexpected format: {next_page_href}"
                    )
            else:
                logging.info(
                    "No 'rel=next' link found on the page."
                )  # Expected on the last page
        else:
            logging.warning(
                f"Pagination UL (ul.css-1gd80ut) not found on {current_url}"
            )

        current_url = next_page_link_url
        if current_url:
            logging.info(f"Found next page: {current_url}")
            time.sleep(1.5)  # Delay between listing page loads
        else:
            logging.info("No next page link found or max pages reached. Stopping.")
            break

    return all_articles_content


def extract_article_content(article_soup, article_url):
    """
    Extract the content from an article page based on the current HTML structure.

    Args:
        article_soup: BeautifulSoup object of the article page
        article_url: URL of the article for logging purposes

    Returns:
        tuple(str, str, str): A tuple containing the cleaned question text (or None),
                              the cleaned summary text (or None),
                              and the cleaned main content text (or None).
    """
    question_text = None
    summary_text = None
    main_content_text = None
    content_sections = []

    try:
        # Find the main content area that contains all article sections
        content_area = article_soup.find(
            "div", id="content", class_=lambda c: c and "css-" in c
        )

        if not content_area:
            logging.warning(f"Main content area not found for {article_url}")
            return None, None, None

        # 1. Extract PERTANYAAN (Question) section
        pertanyaan_section = content_area.find(
            "div", class_=lambda c: c and "css-" in c and "qgav68" in c
        )
        if not pertanyaan_section:
            pertanyaan_section = content_area.find(
                "div", class_=lambda c: c and "css-" in c
            )

        if pertanyaan_section:
            question_div = pertanyaan_section.find(
                "div", class_=lambda c: c and "css-" in c and "c816ma" in c
            )
            if not question_div:
                question_div = pertanyaan_section.find(
                    "div", class_=lambda c: c and "css-" in c
                )

            if question_div:
                question_text = question_div.get_text(separator=" ", strip=True)
                logging.info(f"    Extracted PERTANYAAN section for {article_url}")
            else:
                logging.warning(
                    f"    Found PERTANYAAN section but no content div for {article_url}"
                )

        # 2. Find INTISARI JAWABAN (Summary) section
        # Look for the specific div with class css-uf51zq containing the summary
        intisari_section = content_area.find(
            "div", class_=lambda c: c and "css-uf51zq" in c
        )

        if intisari_section:
            # Find the article element inside this div
            article = intisari_section.find(
                "article", class_=lambda c: c and "css-" in c
            )
            if article:
                # Find the specific div with class css-c816ma that contains the actual content
                summary_div = article.find("div", class_=lambda c: c and "c816ma" in c)
                if summary_div:
                    # Extract only the text from this specific div
                    summary_text = summary_div.get_text(separator=" ", strip=True)
                    logging.info(
                        f"    Extracted INTISARI JAWABAN section for {article_url}"
                    )
                else:
                    logging.warning(
                        f"    Found INTISARI article but missing content div for {article_url}"
                    )
            else:
                logging.warning(
                    f"    Found INTISARI section but missing article element for {article_url}"
                )

        # If still not found, try looking for the heading with ID INTISARI_JAWABAN
        if not summary_text:
            intisari_heading = article_soup.find(id="INTISARI_JAWABAN")
            if intisari_heading:
                # Find the parent div with class css-uf51zq
                parent_div = intisari_heading
                while parent_div and not (
                    parent_div.name == "div"
                    and parent_div.get("class")
                    and "css-uf51zq" in parent_div.get("class", [])
                ):
                    parent_div = parent_div.parent

                if parent_div:
                    # Find the article element inside this div
                    article = parent_div.find("article")
                    if article:
                        # Find the div with class css-c816ma
                        summary_div = article.find(
                            "div", class_=lambda c: c and "c816ma" in c
                        )
                        if summary_div:
                            summary_text = summary_div.get_text(
                                separator=" ", strip=True
                            )
                            logging.info(
                                f"    Extracted INTISARI JAWABAN via heading ID for {article_url}"
                            )

        # Last resort fallback if other methods fail
        if not summary_text:
            # Look for any heading containing "INTISARI JAWABAN" text
            intisari_heading = article_soup.find(
                lambda tag: tag.name in ["h2", "h3"]
                and "INTISARI JAWABAN" in tag.get_text()
            )

            if intisari_heading:
                # Navigate upward to find the container div
                parent_div = intisari_heading.parent
                while parent_div and parent_div.name != "div":
                    parent_div = parent_div.parent

                if parent_div:
                    # Look for the article element
                    article = parent_div.find("article")
                    if article:
                        summary_div = article.find(
                            "div", class_=lambda c: c and "c816ma" in c
                        )
                        if summary_div:
                            summary_text = summary_div.get_text(
                                separator=" ", strip=True
                            )
                            logging.info(
                                f"    Extracted INTISARI JAWABAN via text search for {article_url}"
                            )

        # 3. Extract ULASAN LENGKAP (Complete Review) section - main content
        # First try to find by the specific div class
        ulasan_section = content_area.find(
            "div", class_=lambda c: c and "css-" in c and "103zlhi" in c
        )

        # If not found by class, try to find by heading
        if not ulasan_section:
            ulasan_heading = article_soup.find(
                lambda tag: tag.name in ["h2", "h3"]
                and "ULASAN LENGKAP" in tag.get_text()
            )

            if ulasan_heading:
                # Navigate to the parent div that contains the entire section
                parent = ulasan_heading.parent
                while parent and not (
                    parent.name == "div"
                    and parent.get("class")
                    and any("css-103zlhi" in c for c in parent.get("class", []))
                ):
                    parent = parent.parent

                if parent:
                    ulasan_section = parent
                else:
                    # Fallback: just get the parent div regardless of class
                    ulasan_section = ulasan_heading
                    while ulasan_section and ulasan_section.name != "div":
                        ulasan_section = ulasan_section.parent

        if ulasan_section:
            # Improved extraction of full content including all HTML elements
            ulasan_texts = []

            # Get all content divs in the section
            content_divs = ulasan_section.find_all(
                "div", class_=lambda c: c and "css-" in c and "c816ma" in c
            )

            # If no divs with specific class found, try to get all content divs
            if not content_divs:
                content_divs = ulasan_section.find_all(
                    ["div", "article"], class_=lambda c: c and "css-" in c
                )

            for div in content_divs:
                # Remove scripts, styles, iframes
                for element in div.find_all(["script", "style", "iframe"]):
                    element.decompose()

                # Get text with spacing to preserve structure
                text = div.get_text(separator=" ", strip=True)
                if text and len(text) > 50:  # Only add substantial content
                    ulasan_texts.append(text)

            # If ulasan_texts is not empty, join them
            if ulasan_texts:
                main_content_text = " ".join(ulasan_texts)
                logging.info(f"    Extracted ULASAN LENGKAP section for {article_url}")
            else:
                # If no content divs found, extract all text from the section
                # Clean up content first
                for element in ulasan_section.find_all(["script", "style", "iframe"]):
                    element.decompose()

                main_content_text = ulasan_section.get_text(separator=" ", strip=True)
                # Remove the heading "ULASAN LENGKAP" from the text
                main_content_text = main_content_text.replace(
                    "ULASAN LENGKAP", "", 1
                ).strip()
                if main_content_text:
                    logging.info(
                        f"    Extracted ULASAN LENGKAP full section for {article_url}"
                    )

        # If we have summary but no main content, use summary as main content too
        if summary_text and not main_content_text:
            main_content_text = "INTISARI JAWABAN: " + summary_text
            logging.info(f"    Using summary as main content for {article_url}")
        # If we have main content but no summary, extract summary from main content
        elif (
            main_content_text
            and not summary_text
            and "INTISARI JAWABAN" in main_content_text
        ):
            # Try to extract summary from main content
            parts = main_content_text.split("INTISARI JAWABAN:", 1)
            if len(parts) > 1:
                summary_part = parts[1].strip()
                end_marker = "ULASAN LENGKAP:"
                if end_marker in summary_part:
                    summary_text = summary_part.split(end_marker, 1)[0].strip()
                else:
                    # Take the first paragraph or a fixed number of characters
                    summary_text = (
                        summary_part[:500] if len(summary_part) > 500 else summary_part
                    )
                logging.info(
                    f"    Extracted summary from main content for {article_url}"
                )

        # If we have no main content, try a fallback approach
        if not main_content_text:
            logging.warning(
                f"    No main content found for {article_url}, attempting fallback."
            )
            # Find all substantial text in the content area
            main_content_div = None

            # Try to identify the main content area by searching for ULASAN_LENGKAP id
            ulasan_lengkap_id = article_soup.find(id="ULASAN_LENGKAP")
            if ulasan_lengkap_id:
                # Try to find parent content container
                parent = ulasan_lengkap_id.parent
                while parent and parent.name != "body":
                    if parent.name == "div" and "css-103zlhi" in parent.get(
                        "class", []
                    ):
                        main_content_div = parent
                        break
                    parent = parent.parent

            # If we found the main content div, extract all text from it
            if main_content_div:
                # Clean up content
                for element in main_content_div.find_all(["script", "style", "iframe"]):
                    element.decompose()

                main_content_text = main_content_div.get_text(separator=" ", strip=True)
                logging.info(
                    f"    Used ID-based fallback content extraction for {article_url}"
                )
            else:
                # Fallback: look for any substantial text in the content area
                all_text_divs = content_area.find_all(
                    "div", class_=lambda c: c and "css-" in c
                )
                all_texts = []

                for div in all_text_divs:
                    # Skip if this div is the question div we already extracted
                    if question_text and question_text in div.get_text():
                        continue
                    # Skip if this div is the summary div we already extracted
                    if summary_text and summary_text in div.get_text():
                        continue

                    # Clean up content
                    for element in div.find_all(["script", "style", "iframe"]):
                        element.decompose()

                    text = div.get_text(separator=" ", strip=True)
                    if text and len(text) > 100:  # Only add substantial content
                        all_texts.append(text)

                if all_texts:
                    main_content_text = " ".join(all_texts)
                    logging.info(
                        f"    Used fallback content extraction for {article_url}"
                    )

    except Exception as e:
        logging.error(
            f"    Error during content extraction for {article_url}: {e}", exc_info=True
        )

    return question_text, summary_text, main_content_text


if __name__ == "__main__":
    # Set max_pages to None to scrape all pages, or an integer for testing
    # Be mindful of the website's resources if scraping all pages.
    MAX_PAGES_TO_SCRAPE = 8
    logging.info(f"Starting scraper for max {MAX_PAGES_TO_SCRAPE} pages...")

    scraped_data = scrape_hukumonline_tips(max_pages=MAX_PAGES_TO_SCRAPE)

    logging.info(
        f"\nScraping finished. Scraped content from {len(scraped_data)} articles."
    )

    # --- Save the data to a JSON file ---
    output_filename = "hukumonline_tips.json"
    try:
        with open(output_filename, "w", encoding="utf-8") as f:
            json.dump(scraped_data, f, ensure_ascii=False, indent=2)
        logging.info(f"Data saved to {output_filename}")
    except IOError as e:
        logging.error(f"Error saving data to {output_filename}: {e}")

    # --- Optional: Print summary of the first few articles ---
    if scraped_data:
        print("\n--- Preview of Scraped Data ---")
        for i, article in enumerate(scraped_data[:3]):  # Print preview of first 3
            print(f"\nArticle {i + 1}:")
            print(f"  URL: {article['url']}")
            print(f"  Judul: {article['judul']}")
            preview_length = 300
            content_preview = article["konten"][:preview_length]
            if len(article["konten"]) > preview_length:
                content_preview += "..."
            print(f"  Konten Preview: {content_preview}")
    else:
        print("\nNo data was scraped.")
