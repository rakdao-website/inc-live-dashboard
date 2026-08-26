import re

def validate_initiate(data):
    name = data.get("name")
    email = data.get("email")
    existing_customer = data.get("existingCustomer")

    if not name or not isinstance(name, str):
        return "Name is required"
    if not email or not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        return "Valid email is required"
    if existing_customer is None or not isinstance(existing_customer, bool):
        return "existingCustomer must be boolean"
    return None