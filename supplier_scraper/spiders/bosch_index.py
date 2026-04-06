import re
from urllib.parse import urljoin

from scrapy.spiders import SitemapSpider


class BoschIndexSpider(SitemapSpider):
    name = "bosch_index"
    allowed_domains = [
        "bosch-homecomfort.com",
        "bosch-es-es-c.boschhc-documents.com",
        "b5-web-product-data-service.azurewebsites.net",
    ]

    sitemap_urls = [
        "https://www.bosch-homecomfort.com/sitemaps/sitemapindex/index.xml",
    ]

    sitemap_rules = [
        (r"/es/es/ocs/.+-p/?$", "parse_product"),
    ]

    custom_settings = {
        "ROBOTSTXT_OBEY": True,
    }

    def parse_product(self, response):
        text = self._compact_text(response)

        name = self._clean(response.css("h1::text").get())
        if not name:
            return

        breadcrumbs = [
            self._clean(x)
            for x in response.css("ol li a::text, nav li a::text").getall()
            if self._clean(x)
        ]
        category = " > ".join(breadcrumbs[-3:]) if breadcrumbs else ""

        order_number = self._search_group(
            text,
            r"Número de pedido\s+(\d{8,14})",
        )

        product_type = self._search_group(
            text,
            r"Tipo de producto\s+(.+?)\s+ERP",
        )

        variants = self._search_group(
            text,
            r"Comparación de variantes\s+(.+?)\s+Documentos",
        )

        image_url = self._extract_image_url(response)

        tech_pdf_url = ""
        product_pdf_url = ""
        catalog_pdf_url = ""
        docs_url = ""
        label_png_url = ""

        for a in response.xpath("//a[@href]"):
            href = a.xpath("./@href").get("")
            href = urljoin(response.url, href.strip())
            label = self._clean(" ".join(a.xpath(".//text()").getall()))
            label_low = label.lower()

            if not href:
                continue

            if "ficha técnica" in label_low and href.lower().endswith(".pdf"):
                tech_pdf_url = tech_pdf_url or href
                continue

            if "catálogo" in label_low and href.lower().endswith(".pdf"):
                catalog_pdf_url = catalog_pdf_url or href
                continue

            if "mostrar ahora" in label_low and "boschhc-documents.com" in href:
                docs_url = docs_url or href
                continue

            if "descargar ahora" in label_low and href.lower().endswith(".png"):
                label_png_url = label_png_url or href
                continue

            if "descargar ahora" in label_low and href.lower().endswith(".pdf"):
                if "b5-web-product-data-service" in href:
                    product_pdf_url = product_pdf_url or href

        file_urls = self._dedupe(
            [
                tech_pdf_url,
                product_pdf_url,
            ]
        )

        yield {
            "brand": "bosch",
            "supplier_ref": order_number,
            "name": name,
            "category": category,
            "source_url": response.url,
            "image_url": image_url,
            "pdf_url": tech_pdf_url or product_pdf_url or "",
            "image_urls": [image_url] if image_url else [],
            "file_urls": file_urls,
            "order_number": order_number,
            "product_type": product_type,
            "variants": variants,
            "docs_url": docs_url,
            "product_pdf_url": product_pdf_url,
            "catalog_pdf_url": catalog_pdf_url,
            "label_png_url": label_png_url,
            "search_text": text[:4000],
        }

    def _extract_image_url(self, response):
        candidates = [
            response.css("meta[property='og:image']::attr(content)").get(),
            response.css("img[src*='/ocsmedia/']::attr(src)").get(),
            response.css("source[srcset*='/ocsmedia/']::attr(srcset)").get(),
        ]

        for candidate in candidates:
            if not candidate:
                continue

            candidate = candidate.split(",")[0].strip()
            candidate = candidate.split()[0].strip()
            if candidate:
                return urljoin(response.url, candidate)

        return ""

    def _compact_text(self, response):
        parts = response.css("body *::text").getall()
        return self._clean(" ".join(parts))

    def _search_group(self, text, pattern):
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if not match:
            return ""
        return self._clean(match.group(1))

    def _clean(self, value):
        if not value:
            return ""
        return re.sub(r"\s+", " ", value).strip()

    def _dedupe(self, values):
        seen = set()
        result = []
        for value in values:
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            result.append(value)
        return result
    