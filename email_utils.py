# email_utils.py -- shared Flask-Mail instance + send helper for FR-B1/FR-B4/FR-E2.

from flask_mail import Mail, Message

mail = Mail()


# recipients is always a list -- Flask-Mail requires it even for a single address.
def send_email(subject, recipients, body):
    mail.send(Message(subject=subject, recipients=recipients, body=body))
