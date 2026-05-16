from setuptools import find_packages, setup

with open("README.md", encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="glyphos-ai-compute",
    version="0.6.0",
    author="GlyphOS Team",
    description="Glyph layer and AI routing for local and external compute backends",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/soulhash-labs/public-glyphos-ai-compute",
    packages=find_packages(include=["glyphos_ai*"]),
    package_data={"glyphos_ai": ["config/*.yaml", "glyph/*.yaml"]},
    include_package_data=True,
    install_requires=[
        "PyYAML>=6.0",
        "requests>=2.31.0",
    ],
    python_requires=">=3.8",
    entry_points={
        "console_scripts": [
            "glyph-encode=glyphos_ai.glyph.encoder:main",
            "glyph-route=glyphos_ai.ai_compute.router:main",
        ]
    },
)
