"""Dataset contract: columns, types, allowed values, reason codes."""

SOURCE_COLUMNS = [
    "unique_key", "created_date", "closed_date", "agency", "complaint_type",
    "descriptor", "incident_zip", "incident_address", "borough",
    "community_board", "status", "resolution_description",
    "latitude", "longitude",
]

# columns whose absence means the source schema changed
REQUIRED_COLUMNS = [
    "unique_key", "created_date", "agency", "complaint_type",
    "incident_zip", "borough",
]

# columns that define "same call reported twice"
CONTENT_COLUMNS = [
    "created_date", "agency", "complaint_type", "descriptor",
    "incident_address", "community_board", "latitude", "longitude",
]

VALID_BOROUGHS = {"BRONX", "BROOKLYN", "MANHATTAN", "QUEENS", "STATEN ISLAND"}

# column -> (dtype, nullable); unique key is unique_key
CONTRACT = {
    "unique_key": ("str", False),
    "created_date": ("datetime", False),
    "closed_date": ("datetime", True),
    "agency": ("str", False),
    "complaint_type": ("str", False),
    "descriptor": ("str", False),
    "incident_zip": ("str5", False),
    "incident_address": ("str", True),
    "borough": ("category", False),
    "community_board": ("str", True),
    "status": ("str", True),
    "resolution_description": ("str", True),
    "latitude": ("float", True),
    "longitude": ("float", True),
    "closing_hours": ("float>=0", True),
    "is_closed": ("bool", False),
    "year_month": ("str", False),
    "population": ("float", True),
}

CURATED_COLUMNS = list(CONTRACT.keys())
QUARANTINE_COLUMNS = SOURCE_COLUMNS + ["reason_codes"]

# quarantine reason codes
MISSING_KEY = "MISSING_KEY"
BAD_CREATED_DATE = "BAD_CREATED_DATE"
CREATED_OUT_OF_WINDOW = "CREATED_OUT_OF_WINDOW"
BAD_CLOSED_DATE = "BAD_CLOSED_DATE"
CLOSED_BEFORE_CREATED = "CLOSED_BEFORE_CREATED"
INVALID_ZIP = "INVALID_ZIP"
MISSING_AGENCY = "MISSING_AGENCY"
MISSING_COMPLAINT_TYPE = "MISSING_COMPLAINT_TYPE"
UNKNOWN_BOROUGH = "UNKNOWN_BOROUGH"
BAD_COORDINATES = "BAD_COORDINATES"
DUPLICATE_KEY = "DUPLICATE_KEY"
DUPLICATE_CONTENT = "DUPLICATE_CONTENT"