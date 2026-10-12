"""Hand-written records in the shape the DataSF SODA API returns.

Names, permits and addresses are fictional. Violation text follows the
dataset's "<codes> - <description>., <codes> - <description>." layout.
"""

WAREHOUSE_VIOLATIONS = (
    "114067(f, g), 114099, 114099.3 - Provide an approved warewashing "
    "facility. Obtain chlorine test strips., "
    "114254-114254.2 - Administer all pesticides through a state licensed "
    "pest control operator., "
    "- Submit Standard Operating Procedures for review and approval."
)

CLOSURE_VIOLATIONS = (
    "114259.1, 114259.4 - Eliminate all vermin activity., "
    "- PERMIT SUSPENSION: facility closed due to vermin infestation."
)


def record(permit, date, **fields):
    base = {
        "permit_number": permit,
        "inspection_date": f"{date}T00:00:00.000",
        "inspection_type": "Routine",
        "permit_type": "H25 - RESTAURANT 1,000 - 2,000 SQFT",
        "supervisor_district": "6",
        "latitude": "37.77",
        "longitude": "-122.41",
        "data_as_of": "2026-01-01T00:00:00.000",
    }
    base.update(fields)
    return base


RECORDS = [
    # Rated Pass, then a later Site Visit that carries no rating.
    record(
        "P001",
        "2025-04-10",
        dba="TEST NOODLE HOUSE",
        street_address="100 EXAMPLE ST",
        analysis_neighborhood="Mission",
        facility_rating_status="Pass",
        violation_count="3",
        violation_codes=WAREHOUSE_VIOLATIONS,
    ),
    record(
        "P001",
        "2025-05-27",
        dba="TEST NOODLE HOUSE",
        street_address="100 EXAMPLE ST",
        analysis_neighborhood="Mission",
        inspection_type="Site Visit",
    ),
    # Closure, followed by a Pass re-inspection.
    record(
        "P002",
        "2025-01-15",
        dba="JOE'S TEST DINER",
        street_address="200 SAMPLE AVE",
        analysis_neighborhood="Mission",
        facility_rating_status="Closure",
        violation_count="2",
        violation_codes=CLOSURE_VIOLATIONS,
    ),
    record(
        "P002",
        "2025-01-20",
        dba="JOE'S TEST DINER",
        street_address="200 SAMPLE AVE",
        analysis_neighborhood="Mission",
        inspection_type="Reinspection",
        facility_rating_status="Pass",
        violation_count="0",
    ),
    # Only ever had unrated visits, and no neighborhood.
    record(
        "P003",
        "2025-03-01",
        dba="TEST PLAN CHECK KITCHEN",
        street_address="300 PLACEHOLDER WAY",
        inspection_type="Plan Check",
    ),
    # Conditional Pass in another neighborhood.
    record(
        "P004",
        "2025-02-02",
        dba="NOODLE TEST BAR",
        street_address="400 FIXTURE BLVD",
        analysis_neighborhood="Sunset/Parkside",
        facility_rating_status="Conditional Pass",
        violation_count="1",
        violation_codes="114130 - Provide adequate hand washing facilities.",
    ),
]
