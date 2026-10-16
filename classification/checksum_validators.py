"""Checksum validators for candidate sensitive identifiers."""


def passes_luhn(value: object) -> bool:
    """Return whether a digit string passes the Luhn checksum.

    Spaces and hyphens are ignored. Other non-digit characters cause
    the input to be rejected. A passing checksum does not establish
    that a number is an actual or active payment card.
    """
    if not isinstance(value, str):
        return False

    candidate = value.strip()

    if not candidate:
        return False

    digits = candidate.replace(" ", "").replace("-", "")

    if not digits.isdigit():
        return False

    if not 13 <= len(digits) <= 19:
        return False

    total = 0
    parity = len(digits) % 2

    for index, character in enumerate(digits):
        digit = int(character)

        if index % 2 == parity:
            digit *= 2
            if digit > 9:
                digit -= 9

        total += digit

    return total % 10 == 0
def passes_npi_checksum(value: object) -> bool:
    """Return whether a 10-digit NPI passes its checksum.

    The NPI checksum uses the Luhn algorithm with the prefix 80840.
    Passing the checksum does not establish that the NPI is assigned
    or active.
    """
    if not isinstance(value, str):
        return False

    candidate = value.strip()

    if len(candidate) != 10 or not candidate.isdigit():
        return False

    return passes_luhn("80840" + candidate)