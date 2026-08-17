# email_utils.py -- shared Flask-Mail instance + send helper for FR-B1/FR-B4/FR-E2.

from flask_mail import Mail, Message

mail = Mail()


# recipients is always a list -- Flask-Mail requires it even for a single address.
# attachment_path/attachment_filename are optional, used by FR-D1 to attach the invoice PDF.
def send_email(subject, recipients, body, attachment_path=None, attachment_filename=None):
    message = Message(subject=subject, recipients=recipients, body=body)
    if attachment_path is not None:
        with open(attachment_path, "rb") as pdf_file:
            message.attach(attachment_filename, "application/pdf", pdf_file.read())
    mail.send(message)
