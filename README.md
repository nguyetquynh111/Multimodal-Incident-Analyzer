# Multimodal Incident Analyzer

This project is a class prototype for analyzing multimodal incident evidence. It is designed to process separate audio, PDF, image, video, and text outputs, merge them into one incident dataset, apply severity rules, and display the results in a Streamlit dashboard.

## Repository Structure

```text
multimodal-incident-analyzer/
|-- audio/
|   |-- process_audio.py
|   `-- audio_output.csv
|-- pdf/
|   |-- process_pdf.py
|   `-- pdf_output.csv
|-- images/
|   |-- process_images.py
|   `-- image_output.csv
|-- video/
|   |-- process_video.py
|   `-- video_output.csv
|-- text/
|   |-- process_text.py
|   `-- text_output.csv
|-- integration/
|   |-- merge_outputs.py
|   |-- severity_rules.py
|   `-- final_incident_dataset.csv
|-- dashboard/
|   `-- app.py
|-- figures/
|   |-- data_flow.png
|   `-- system_architecture.png
|-- requirements.txt
`-- README.md
```

## Setup

Install the project dependencies:

```bash
pip install -r requirements.txt
```

## Run

Merge modality outputs into the final incident dataset:

```bash
python integration/merge_outputs.py
```

Launch the Streamlit dashboard:

```bash
streamlit run dashboard/app.py
```

## Expected Output

The integration step should create or update:

```text
integration/final_incident_dataset.csv
```

The dashboard should read the final incident dataset and provide a simple interface for reviewing incidents and severity results.
