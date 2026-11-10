from email import message_from_bytes
from email.policy import default
from email.message import EmailMessage
import base64


def test_gmail_raw_mime_message_roundtrip():
    msg = EmailMessage()
    msg["To"] = "person@example.com"
    msg["Subject"] = "Hello"
    msg.set_content("Test body")
    msg.add_attachment(b"sample", maintype="application", subtype="pdf", filename="cv.pdf")
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    decoded = base64.urlsafe_b64decode(raw.encode())
    parsed = message_from_bytes(decoded, policy=default)
    assert parsed["To"] == "person@example.com"
    assert parsed["Subject"] == "Hello"
    parts = list(parsed.iter_attachments())
    assert len(parts) == 1
    assert parts[0].get_filename() == "cv.pdf"
    assert parts[0].get_content() == b"sample"
