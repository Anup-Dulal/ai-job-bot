"""
resume_profile.py — Single source of truth extracted from Anup's resume.
Groq uses this to generate search queries and score jobs intelligently.
"""

RESUME = {
    "name": "Anup Dulal",
    "email": "Anupdulal2012@gmail.com",
    "phone": "+917455896497",
    "location": "Ghaziabad, UP (open to relocation anywhere in India)",
    "title": "Java Backend Developer",
    "experience_years": 4,
    "current_company": "Capgemini Technology Services",
    "current_client": "Disney",
    "notice_period": "60 days",
    "expected_ctc": "9-10 LPA",
    "education": "B.Tech Computer Science, IIMT University Meerut, 2021",
    "certifications": ["AWS Certified Cloud Practitioner"],
    "awards": ["Client Appreciation", "Idea Innovation Award"],

    "skills": {
        "languages": ["Java", "Python", "C++"],
        "frameworks": ["Spring", "Spring Boot", "JUnit", "Mockito", "REST APIs", "React"],
        "cloud": ["AWS EC2", "AWS S3"],
        "observability": ["AppDynamics", "Splunk", "Grafana"],
        "ai_tools": ["Amazon Q", "GitHub Copilot", "Kiro"],
        "methodologies": ["Agile", "Scrum", "OOP", "Microservices Architecture"],
        "databases": ["SQL"],
        "tools": ["Git", "Eclipse", "VS Code", "Spring Tool Suite"],
    },

    "experience": [
        {
            "company": "Capgemini Technology Services",
            "client": "Disney",
            "role": "Associate Consultant (Java Backend Developer)",
            "duration": "Jan 2022 - Present",
            "highlights": [
                "Led end-to-end backend feature delivery from offshore team for Disney enterprise platforms",
                "Built scalable microservices using Java 17 and Spring Boot 2.7",
                "Developed RESTful API endpoints for enterprise systems",
                "Java 8 to 17 and Spring Boot 1.5 to 2.7 migration on live systems",
                "Python script for cache optimization reducing application load times",
                "Unit testing with JUnit and Mockito improving code quality",
                "Production monitoring with Splunk, AppDynamics, Grafana",
                "Mentored junior developers, collaborated with global onshore teams",
            ],
        }
    ],

    "projects": [
        "Online Crop Deal System — Spring Boot, React, Microservices",
        "Mask Detection System — Python, ML, OpenCV, YOLO",
        "Speech Emotion Recognition — Python, CNN, Ravdess/Tess dataset",
    ],

    "summary": (
        "Results-driven Java Backend Developer with 4+ years delivering scalable enterprise applications "
        "using Spring Boot, Microservices, and AWS at Capgemini for Disney. "
        "AWS Certified Cloud Practitioner. Strong in REST APIs, JUnit/Mockito testing, "
        "Java migrations, production monitoring with Splunk/AppDynamics. "
        "Actively uses AI tools: Amazon Q, GitHub Copilot, Kiro."
    ),

    "ideal_job": {
        "roles": [
            "Java Backend Developer",
            "Java Developer",
            "Spring Boot Developer",
            "Backend Engineer",
            "Software Engineer - Java",
            "Microservices Developer",
            "Associate Software Engineer",
            "Senior Software Engineer",
        ],
        "locations": ["Noida", "Gurgaon", "Delhi NCR", "Bangalore", "Hyderabad", "Remote"],
        "exp_range": "3-6 years",
        "company_type": "product company or good MNC (not body shop/staffing)",
        "avoid": ["staffing", "recruitment", "placement", "body shop"],
    },
}


def get_resume_text() -> str:
    """Return resume as plain text for Groq prompts."""
    skills_flat = (
        RESUME["skills"]["languages"] +
        RESUME["skills"]["frameworks"] +
        RESUME["skills"]["cloud"] +
        RESUME["skills"]["methodologies"]
    )
    return f"""
Name: {RESUME['name']}
Title: {RESUME['title']}
Experience: {RESUME['experience_years']}+ years
Current: {RESUME['current_company']} (client: {RESUME['current_client']})
Skills: {', '.join(skills_flat)}
Certifications: {', '.join(RESUME['certifications'])}
Education: {RESUME['education']}
Notice: {RESUME['notice_period']} | Expected CTC: {RESUME['expected_ctc']}
Summary: {RESUME['summary']}
"""
