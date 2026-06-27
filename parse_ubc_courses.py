import json
import re
from copy import deepcopy

# =========================================================
# CONFIG
# =========================================================

INPUT_FILE = "ubc_courses.json"
OUTPUT_FILE = "ubc_courses_structured.json"

COURSE_PATTERN = r"[A-Z]{2,5}_?V?\s*\d{3}"

# =========================================================
# UTILITIES
# =========================================================

def clean_text(text):

    text = text.replace("\n", " ")
    text = re.sub(r"\s+", " ", text)

    return text.strip()


def normalize_course(course):

    course = course.replace("_V", " ")

    m = re.match(
        r"([A-Z]{2,5})\s*(\d{3})",
        course
    )

    if m:
        return f"{m.group(1)} {m.group(2)}"

    return re.sub(r"\s+", " ", course).strip()


# =========================================================
# AST HELPERS
# =========================================================

def course_node(course):

    return {
        "type": "COURSE",
        "course": normalize_course(course)
    }


def grade_node(course, grade):

    return {
        "type": "GRADE",
        "course": normalize_course(course),
        "min_grade": grade
    }


def and_node(conditions):

    return {
        "type": "AND",
        "conditions": conditions
    }


def or_node(conditions):

    return {
        "type": "OR",
        "conditions": conditions
    }


def standing_node(year):

    return {
        "type": "YEAR_STANDING",
        "min_year": year
    }


def subject_credit_node(subject, credits):

    return {
        "type": "SUBJECT_CREDITS",
        "subject": subject,
        "min_credits": credits
    }


# =========================================================
# HOURS
# =========================================================

def extract_hours(desc):

    m = re.search(
        r"\[(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\s*[-–]\s*(\d+(?:\.\d+)?)\]",
        desc
    )

    if not m:
        return None

    return {
        "lecture": float(m.group(1)),
        "lab": float(m.group(2)),
        "tutorial": float(m.group(3))
    }


# =========================================================
# CREDIT/D/FAIL
# =========================================================

def extract_credit_d_fail(desc):

    if "not eligible for Credit/D/Fail grading" in desc:
        return False

    return True


# =========================================================
# EXCLUSIONS
# =========================================================

def extract_exclusions(desc):

    exclusions = []

    patterns = [
        r"Not for students with existing credit for or exemption from (.+?)\.",
        r"Not for credit for students who have credit for, or exemption from, or are concurrently taking (.+?)\.",
        r"Credit will be granted for only one of (.+?)\.",
        r"A maximum of .* credits will be granted for (.+?)\.",
    ]

    for pattern in patterns:

        matches = re.finditer(pattern, desc, re.IGNORECASE)

        for match in matches:

            courses = re.findall(
                COURSE_PATTERN,
                match.group(1)
            )

            exclusions.extend([
                normalize_course(c)
                for c in courses
            ])

    return sorted(list(set(exclusions)))


# =========================================================
# RESTRICTIONS
# =========================================================

def extract_restrictions(desc):

    restrictions = {}

    # -----------------------------------------------------
    # faculty
    # -----------------------------------------------------

    m = re.search(
        r"Restricted to students in the Faculty of ([A-Za-z ]+)",
        desc,
        re.IGNORECASE
    )

    if m:

        restrictions["faculty"] = (
            m.group(1).strip()
        )

    # -----------------------------------------------------
    # program
    # -----------------------------------------------------

    m = re.search(
        r"Restricted to students in the (.+?) program",
        desc,
        re.IGNORECASE
    )

    if m:

        restrictions["program"] = (
            m.group(1).strip()
        )

    # -----------------------------------------------------
    # specialization
    # -----------------------------------------------------

    m = re.search(
        r"Only open to students in a (.+?) specialization",
        desc,
        re.IGNORECASE
    )

    if m:

        restrictions["program"] = (
            m.group(1).strip()
        )

    if restrictions:
        return restrictions

    return None


# =========================================================
# SPLIT HELPERS
# =========================================================

def split_top_level_and(text):

    result = []

    current = ""

    depth = 0

    tokens = text.split()

    for token in tokens:

        lower = token.lower()

        depth += token.count("(")
        depth -= token.count(")")

        if lower == "and" and depth == 0:

            result.append(current.strip())
            current = ""

        else:
            current += " " + token

    if current.strip():
        result.append(current.strip())

    return result


def split_top_level_or(text):

    result = []

    current = ""

    depth = 0

    tokens = text.split()

    for token in tokens:

        lower = token.lower()

        depth += token.count("(")
        depth -= token.count(")")

        if lower == "or" and depth == 0:

            result.append(current.strip())
            current = ""

        else:
            current += " " + token

    if current.strip():
        result.append(current.strip())

    return result


# =========================================================
# LETTERED GROUPS
# =========================================================

def parse_lettered_groups(text, global_min_grade=None):

    pattern = r"\([a-z]\)"

    matches = list(re.finditer(pattern, text))

    if not matches:
        return None

    groups = []

    for i, match in enumerate(matches):

        start = match.end()

        if i + 1 < len(matches):
            end = matches[i + 1].start()
        else:
            end = len(text)

        group_text = text[start:end].strip(" ,.")

        parsed = parse_requirement(
            group_text,
            inherited_min_grade=global_min_grade
        )

        groups.append(parsed)

    return and_node(groups)


# =========================================================
# SIMPLE PARSERS
# =========================================================

def parse_grade_requirement(text):

    m = re.search(
        r"(\d+)%\s*or higher in\s*(" + COURSE_PATTERN + ")",
        text,
        re.IGNORECASE
    )

    if not m:
        return None

    return grade_node(
        m.group(2),
        int(m.group(1))
    )


def parse_standing_requirement(text):

    patterns = [
        (r"first[- ]year standing", 1),
        (r"second[- ]year standing", 2),
        (r"third[- ]year standing", 3),
        (r"fourth[- ]year standing", 4),
    ]

    for pattern, year in patterns:

        if re.search(pattern, text, re.IGNORECASE):

            return standing_node(year)

    return None


def parse_credit_requirement(text):

    # -----------------------------------------------------
    # combined subjects
    # -----------------------------------------------------

    m = re.search(
        r"(\d+)\s+credits?\s+of\s+(.+?)\s+courses?",
        text,
        re.IGNORECASE
    )

    if m:

        credits = int(m.group(1))

        subject_text = m.group(2)

        subjects = re.findall(
            r"[A-Z]{2,5}",
            subject_text
        )

        if len(subjects) > 1:

            return {
                "type": "COMBINED_SUBJECT_CREDITS",
                "subjects": subjects,
                "min_credits": credits
            }

        elif len(subjects) == 1:

            return {
                "type": "SUBJECT_CREDITS",
                "subject": subjects[0],
                "min_credits": credits
            }

    # -----------------------------------------------------
    # fallback
    # -----------------------------------------------------

    m = re.search(
        r"(\d+)\s+credits?\s+of\s+([A-Z]{2,5}|Computer Science)",
        text,
        re.IGNORECASE
    )

    if not m:
        return None

    subject = m.group(2)

    if subject.lower() == "computer science":
        subject = "CPSC"

    return {
        "type": "SUBJECT_CREDITS",
        "subject": subject.upper(),
        "min_credits": int(m.group(1))
    }


def parse_permission_requirement(text):

    if "permission of instructor" in text.lower():

        return {
            "type": "INSTRUCTOR_PERMISSION"
        }

    return None


# =========================================================
# MAIN REQUIREMENT PARSER
# =========================================================

def parse_requirement(text, inherited_min_grade=None):

    text = clean_text(text)

    text = text.rstrip(".")

    # =====================================================
    # minimum grade in each of
    # =====================================================

    grade_each_match = re.search(
        r"minimum grade of (\d+)% in each of:(.+)",
        text,
        re.IGNORECASE
    )

    if grade_each_match:

        min_grade = int(
            grade_each_match.group(1)
        )

        remaining = grade_each_match.group(2)

        return parse_lettered_groups(
            remaining,
            global_min_grade=min_grade
        )

    # =====================================================
    # lettered groups
    # =====================================================

    lettered = parse_lettered_groups(
        text,
        global_min_grade=inherited_min_grade
    )

    if lettered:
        return lettered

    # =====================================================
    # top level AND
    # =====================================================

    and_parts = split_top_level_and(text)

    if len(and_parts) > 1:

        return and_node([
            parse_requirement(
                p,
                inherited_min_grade=inherited_min_grade
            )
            for p in and_parts
        ])

    # =====================================================
    # one of
    # =====================================================

    if text.lower().startswith("one of"):

        remaining = text[6:].strip()

        courses = re.findall(
            COURSE_PATTERN,
            remaining
        )

        conditions = []

        for c in courses:

            node = course_node(c)

            if inherited_min_grade is not None:
                node["min_grade"] = inherited_min_grade

            conditions.append(node)

        return or_node(conditions)

    # =====================================================
    # all of
    # =====================================================

    if text.lower().startswith("all of"):

        remaining = text[6:].strip()

        return parse_requirement(
            remaining,
            inherited_min_grade=inherited_min_grade
        )

    # =====================================================
    # either ... or ...
    # =====================================================

    if text.lower().startswith("either"):

        remaining = text[6:].strip()

        remaining = re.sub(
            r"\([a-z]\)",
            "|SPLIT|",
            remaining
        )

        if "|SPLIT|" in remaining:

            parts = [
                p.strip(" ,.")
                for p in remaining.split("|SPLIT|")
                if p.strip()
            ]

        else:

            parts = split_top_level_or(
                remaining
            )

        return or_node([
            parse_requirement(
                p,
                inherited_min_grade=inherited_min_grade
            )
            for p in parts
        ])

    # =====================================================
    # grade requirement
    # =====================================================

    grade_req = parse_grade_requirement(text)

    if grade_req:
        return grade_req

    # =====================================================
    # standing
    # =====================================================

    standing = parse_standing_requirement(text)

    if standing:
        return standing

    # =====================================================
    # credit requirement
    # =====================================================

    credit_req = parse_credit_requirement(text)

    if credit_req:
        return credit_req

    # =====================================================
    # instructor permission
    # =====================================================

    permission = parse_permission_requirement(text)

    if permission:
        return permission

    # =====================================================
    # top level OR
    # =====================================================

    or_parts = split_top_level_or(text)

    if len(or_parts) > 1:

        return or_node([
            parse_requirement(
                p,
                inherited_min_grade=inherited_min_grade
            )
            for p in or_parts
        ])

    # =====================================================
    # multiple courses
    # =====================================================

    courses = re.findall(
        COURSE_PATTERN,
        text
    )

    if len(courses) > 1:

        conditions = []

        for c in courses:

            node = course_node(c)

            if inherited_min_grade is not None:
                node["min_grade"] = inherited_min_grade

            conditions.append(node)

        return or_node(conditions)

    # =====================================================
    # single course
    # =====================================================

    if len(courses) == 1:

        node = course_node(courses[0])

        if inherited_min_grade is not None:
            node["min_grade"] = inherited_min_grade

        return node

    # =====================================================
    # fallback
    # =====================================================

    return {
        "type": "TEXT",
        "value": text
    }


# =========================================================
# FIELD EXTRACTION
# =========================================================

def extract_field(desc, field_name):

    pattern = rf"{field_name}:\s*(.+?)(?=(Corequisite:|Prerequisite:|Equivalency:|Restricted to|Only open to|This course|Credit will|$))"

    m = re.search(
        pattern,
        desc,
        re.IGNORECASE
    )

    if not m:
        return None

    return clean_text(m.group(1))


def extract_prerequisites(desc):

    text = extract_field(
        desc,
        "Prerequisite"
    )

    if not text:
        return None

    return parse_requirement(text)


def extract_corequisites(desc):

    text = extract_field(
        desc,
        "Corequisite"
    )

    if not text:
        return None

    return parse_requirement(text)


def extract_equivalencies(desc):

    m = re.search(
        r"Equivalency:\s*(.+?)(?:\.|$)",
        desc,
        re.IGNORECASE
    )

    if not m:
        return []

    courses = re.findall(
        COURSE_PATTERN,
        m.group(1)
    )

    return [
        normalize_course(c)
        for c in courses
    ]


# =========================================================
# MAIN
# =========================================================

with open(INPUT_FILE, "r", encoding="utf-8") as f:

    data = json.load(f)

new_data = deepcopy(data)

for faculty, courses in new_data.items():

    for course in courses:

        desc = clean_text(
            course.get("description", "")
        )

        # =================================================
        # raw
        # =================================================

        course["raw_description"] = desc

        # =================================================
        # hours
        # =================================================

        course["hours"] = extract_hours(desc)

        # =================================================
        # credit/d/fail
        # =================================================

        course["credit_d_fail_allowed"] = (
            extract_credit_d_fail(desc)
        )

        # =================================================
        # exclusions
        # =================================================

        course["exclusions"] = (
            extract_exclusions(desc)
        )

        # =================================================
        # restrictions
        # =================================================

        course["restrictions"] = (
            extract_restrictions(desc)
        )

        # =================================================
        # prerequisites
        # =================================================

        course["prerequisites"] = (
            extract_prerequisites(desc)
        )

        # =================================================
        # corequisites
        # =================================================

        course["corequisites"] = (
            extract_corequisites(desc)
        )

        # =================================================
        # equivalencies
        # =================================================

        course["equivalencies"] = (
            extract_equivalencies(desc)
        )

# =========================================================
# SAVE
# =========================================================

with open(OUTPUT_FILE, "w", encoding="utf-8") as f:

    json.dump(
        new_data,
        f,
        indent=2,
        ensure_ascii=False
    )

print(f"Done -> {OUTPUT_FILE}")