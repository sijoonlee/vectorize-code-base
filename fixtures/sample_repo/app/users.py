class UserValidator:
    def validate_email(self, email: str) -> bool:
        return "@" in email and "." in email


def normalize_user_name(name: str) -> str:
    return " ".join(name.strip().split()).title()
