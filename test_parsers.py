import os
import shutil
import unittest
from app.core.parser import detect_mime_type, DocumentParser
from app.core.splitter import RecursiveTextSplitter

class TestParserPipeline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = "test_files"
        # Ensure test files exist (ran generate_test_files.py)
        if not os.path.exists(cls.test_dir) or not os.listdir(cls.test_dir):
            from generate_test_files import create_test_files
            create_test_files()

    def test_mime_detection_no_extensions(self):
        """Verify that we detect MIME types based on headers/signatures, not extensions."""
        test_cases = [
            ("notes.txt", "text/plain"),
            ("sales.csv", "text/csv"),
            ("homepage.html", "text/html"),
            ("readme.md", "text/markdown"),
            ("support_ticket.eml", "message/rfc822"),
        ]
        
        # Test binary signature cases if files were created
        if os.path.exists(os.path.join(self.test_dir, "engineering_handbook.docx")):
            test_cases.append(("engineering_handbook.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"))
        if os.path.exists(os.path.join(self.test_dir, "product_roadmap.pptx")):
            test_cases.append(("product_roadmap.pptx", "application/vnd.openxmlformats-officedocument.presentationml.presentation"))
        if os.path.exists(os.path.join(self.test_dir, "quarterly_earnings.xlsx")):
            test_cases.append(("quarterly_earnings.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"))
        if os.path.exists(os.path.join(self.test_dir, "company_policy.pdf")):
            test_cases.append(("company_policy.pdf", "application/pdf"))

        for filename, expected_mime in test_cases:
            src_path = os.path.join(self.test_dir, filename)
            # Create a copy with NO extension
            temp_path = os.path.join(self.test_dir, f"temp_sniff_{filename}_noext")
            shutil.copy(src_path, temp_path)
            
            try:
                detected = detect_mime_type(temp_path)
                self.assertEqual(detected, expected_mime, f"Failed for {filename}")
            finally:
                if os.path.exists(temp_path):
                    os.remove(temp_path)

    def test_text_parser(self):
        """Test plain text parser parses text and contains specific notes content."""
        path = os.path.join(self.test_dir, "notes.txt")
        doc = DocumentParser.parse(path, "notes.txt")
        self.assertTrue(doc.success)
        self.assertEqual(doc.mime_type, "text/plain")
        self.assertIn("9081#", doc.sections[0].text)
        self.assertEqual(doc.sections[0].metadata["source"], "notes.txt")

    def test_markdown_parser(self):
        """Test markdown parser parses sections based on headers."""
        path = os.path.join(self.test_dir, "readme.md")
        doc = DocumentParser.parse(path, "readme.md")
        self.assertTrue(doc.success)
        self.assertEqual(doc.mime_type, "text/markdown")
        # Check that we parsed headers
        self.assertTrue(len(doc.sections) > 0)
        self.assertTrue(any("RAG System" in s.metadata["section"] for s in doc.sections))

    def test_csv_parser(self):
        """Test CSV parses into markdown tables."""
        path = os.path.join(self.test_dir, "sales.csv")
        doc = DocumentParser.parse(path, "sales.csv")
        self.assertTrue(doc.success)
        self.assertEqual(doc.mime_type, "text/csv")
        self.assertIn("| Region | Manager | Target_Met | Q1_Sales |", doc.sections[0].text)

    def test_html_parser(self):
        """Test HTML parses body elements and strips tags."""
        path = os.path.join(self.test_dir, "homepage.html")
        doc = DocumentParser.parse(path, "homepage.html")
        self.assertTrue(doc.success)
        self.assertEqual(doc.mime_type, "text/html")
        self.assertIn("Empowering document intelligence", doc.sections[0].text)

    def test_eml_parser(self):
        """Test EML email body and header parser."""
        path = os.path.join(self.test_dir, "support_ticket.eml")
        doc = DocumentParser.parse(path, "support_ticket.eml")
        self.assertTrue(doc.success)
        self.assertEqual(doc.mime_type, "message/rfc822")
        self.assertIn("blocked by their firewall", doc.sections[0].text)
        self.assertEqual(doc.sections[0].metadata["headers"]["from"], "support-system@auracorp.example.com")

    def test_graceful_failures(self):
        """Verify corrupt and encrypted PDFs fail gracefully with descriptive error messages instead of crashing."""
        corrupt_path = os.path.join(self.test_dir, "corrupt.pdf")
        doc_corrupt = DocumentParser.parse(corrupt_path, "corrupt.pdf")
        self.assertFalse(doc_corrupt.success)
        self.assertIsNotNone(doc_corrupt.error_message)
        self.assertIn("PyPDF error", doc_corrupt.error_message)

        pwd_path = os.path.join(self.test_dir, "password.pdf")
        doc_pwd = DocumentParser.parse(pwd_path, "password.pdf")
        self.assertFalse(doc_pwd.success)
        self.assertIsNotNone(doc_pwd.error_message)
        self.assertIn("password-protected", doc_pwd.error_message)

    def test_splitter_logic(self):
        """Test that chunks are within sizes and inherit parent metadata."""
        path = os.path.join(self.test_dir, "notes.txt")
        doc = DocumentParser.parse(path, "notes.txt")
        
        splitter = RecursiveTextSplitter(chunk_size=100, chunk_overlap=20)
        chunks = splitter.split_document(doc)
        
        self.assertTrue(len(chunks) > 0)
        for chunk in chunks:
            self.assertTrue(len(chunk.text) <= 100)
            self.assertEqual(chunk.metadata["source"], "notes.txt")
            self.assertEqual(chunk.metadata["mime_type"], "text/plain")
            self.assertIn("chunk_index", chunk.metadata)


if __name__ == "__main__":
    unittest.main()
