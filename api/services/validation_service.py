def validate_row_count(rows: int, min_rows: int = 1, max_rows: int = 1000):
    if rows < min_rows or rows > max_rows:
        raise ValueError(f"rows must be between {min_rows} and {max_rows} for this demo")

def validate_sample_size(sample_size: int, min_size: int = 1, max_size: int = 1000):
    return max(min_size, min(sample_size, max_size))
