import os
import json
import pandas as pd
import mysql.connector
from openpyxl import Workbook
from flask import Flask, request, redirect, url_for, send_file, render_template_string

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

# Azure Form Recognizer configuration
AZURE_FORM_RECOGNIZER_ENDPOINT = "https://sitemap-wsu-test-1.cognitiveservices.azure.com/"
AZURE_FORM_RECOGNIZER_KEY = "319cfd9282ed4335b1d7def4a75901e9"
MODEL_ID = "Table_3"  # Your custom model ID

# Initialize the Flask application
app = Flask(__name__)
UPLOAD_FOLDER = 'uploads/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create the upload folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Initialize the Document Analysis Client
document_analysis_client = DocumentAnalysisClient(
    endpoint=AZURE_FORM_RECOGNIZER_ENDPOINT,
    credential=AzureKeyCredential(AZURE_FORM_RECOGNIZER_KEY)
)

# Function to analyze PDF with Azure Document Intelligence
def analyze_pdf_with_azure(filepath):
    with open(filepath, "rb") as f:
        poller = document_analysis_client.begin_analyze_document(
            model_id=MODEL_ID, document=f
        )
        result = poller.result()
    return result

# Function to load JSON data from Azure Form Recognizer result
def get_json_from_azure_result(analysis_result):
    # Convert result to JSON-like structure for parsing
    return json.loads(analysis_result.to_dict())

# Parse client data from JSON and format it into a DataFrame
def parse_client(json_file):
    table = json_file[0]  # Assuming the first table contains client info
    row_count = table['rowCount']
    column_count = table['columnCount']

    df = pd.DataFrame(index=range(column_count - 1), columns=range(row_count + 1))

    for cell in table['cells']:
        row_index = cell.get('rowIndex')
        column_index = cell.get('columnIndex')
        content = cell.get('content')
        if column_index != 0:
            df.iloc[column_index - 1, row_index + 1] = content

    df.columns = ['id', 'name', 'site']

    return df.drop(columns=['id'])  # Remove 'id' column as MySQL will auto-generate it


# Parse location data from JSON and map it to the client
def parse_location(json_file, client_index_map):
    data_frame = pd.DataFrame(index=range(len(json_file) - 1), columns=range(2))

    for i in range(1, len(json_file)):
        table = json_file[i]
        data_frame.iloc[i - 1, 0] = get_location_from_table(table)
        data_frame.iloc[i - 1, 1] = client_index_map['ABC Company']

    data_frame.columns = ['location', 'client']

    return data_frame


# Parse task data from JSON and map it to the location
def parse_tasks(json_file, location_index_map):
    task_number = 0

    # Get the overall number of tasks
    for i in range(1, len(json_file)):
        table = json_file[i]
        task_number += table['rowCount'] - 1

    task_number += 1

    data_frame = pd.DataFrame(index=range(task_number - 1), columns=range(9))

    task_row_grap = 0
    for i in range(1, len(json_file)):
        table = json_file[i]

        for cell in table['cells']:
            row_index = cell.get('rowIndex')
            column_index = cell.get('columnIndex')
            content = cell.get('content')

            location = get_location_from_table(table)

            if row_index != 0:
                data_frame.iloc[row_index + task_row_grap - 1, 0] = location_index_map[location]
                data_frame.iloc[row_index + task_row_grap - 1, column_index + 1] = content

        task_row_grap += table['rowCount'] - 1

    data_frame.columns = ['location', 'description', 'monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday',
                          'sunday']

    return data_frame


# Get location from the first cell in the table
def get_location_from_table(table):
    cells = table['cells']

    for cell in cells:
        if cell.get('rowIndex') == 0 and cell.get('columnIndex') == 0:
            return cell.get('content')
    return "unknown"


# Create a map of index to value for quick lookups
def create_index_map(data_frame, index_col, key_col):
    index_map = {}
    i = 0

    for row in data_frame.iterrows():
        index = data_frame[index_col][i]
        value = data_frame[key_col][i]
        index_map[value] = index
        i += 1
    return index_map


# Clean the data frame to replace NaN with None (which maps to SQL NULL)
def clean_data_frame(data_frame):
    cleaned_df = data_frame.where(pd.notnull(data_frame), None)
    return cleaned_df


## Insert data into MySQL table
def insert_clients_into_sql(table_name, data_frame, conn):
    cursor = conn.cursor()
    data_frame = clean_data_frame(data_frame)

    placeholders = ', '.join(['%s'] * len(data_frame.columns))
    columns = ', '.join(data_frame.columns)

    sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
    cursor.executemany(sql, data_frame.values.tolist())
    conn.commit()

def select_from_sql(table_name, data_frame, conn):
    cursor = conn.cursor()
    columns = 'id,' + ', '.join(data_frame.columns)

    sql = f"SELECT {columns} FROM {table_name}"
    cursor.execute(sql)
    rows = cursor.fetchall()

    # Create a new DataFrame to store the fetched data
    new_data_frame = pd.DataFrame(rows, columns=['id'] + list(data_frame.columns))

    return new_data_frame

def get_table_index(table_name, index_name, field_name, conn):
    cursor = conn.cursor()
    sql = f"SELECT {index_name}, {field_name} FROM {table_name};"
    cursor.execute(sql)

    result = cursor.fetchall()

    index_map = {row[1]: row[0] for row in result}  # Map field_name to index_name
    return index_map


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)
        file = request.files['file']
        if file.filename == '':
            return redirect(request.url)
        if file and file.filename.endswith('.pdf'):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(filepath)

            # Analyze the PDF using Azure Form Recognizer
            analysis_result = analyze_pdf_with_azure(filepath)
            data_json = get_json_from_azure_result(analysis_result)

            # Connect to MySQL database
            conn = mysql.connector.connect(
                host="127.0.0.1",
                user="root",
                password="password",
                database="px_table_7"
            )
            cursor = conn.cursor()

            # Function to get the max ID of a table
            def get_max_id(table_name):
                cursor.execute(f"SELECT MAX(id) FROM {table_name}")
                max_id = cursor.fetchone()[0]
                return max_id if max_id is not None else 0

            # Capture max IDs before insertion
            client_max_id = get_max_id('client')
            location_max_id = get_max_id('location')
            task_max_id = get_max_id('task')

            # Parse and clean client data
            client_data_frame = parse_client(data_json)
            insert_clients_into_sql('client', client_data_frame, conn)
            client_index_map = get_table_index('client', 'id', 'name', conn)

            # Parse and clean location data
            location_data_frame = parse_location(data_json, client_index_map)
            insert_clients_into_sql('location', location_data_frame, conn)
            location_index_map = get_table_index('location', 'id', 'location', conn)

            # Parse and clean task data
            task_data_frame = parse_tasks(data_json, location_index_map)
            insert_clients_into_sql('task', task_data_frame, conn)

            # Function to get newly inserted rows
            def get_new_rows(table_name, last_id):
                query = f"SELECT * FROM {table_name} WHERE id > {last_id}"
                cursor.execute(query)
                result = cursor.fetchall()
                columns = [col[0] for col in cursor.description]
                return pd.DataFrame(result, columns=columns)

            # Retrieve only newly inserted data
            new_client_data_frame = get_new_rows('client', client_max_id)
            new_location_data_frame = get_new_rows('location', location_max_id)
            new_task_data_frame = get_new_rows('task', task_max_id)

            conn.close()

            # Convert DataFrames to HTML tables for rendering
            client_html = new_client_data_frame.to_html(classes='table table-striped', index=False)
            location_html = new_location_data_frame.to_html(classes='table table-striped', index=False)
            task_html = new_task_data_frame.to_html(classes='table table-striped', index=False)

            # Render the template string with the tables
            return render_template_string('''
                <html>
                <head>
                    <style>
                        body {
                            font-family: Arial, sans-serif;
                            background-color: #f4f4f4;
                            margin: 0;
                            padding: 0;
                            display: flex;
                            justify-content: center;
                            align-items: center;
                            height: 100vh;
                            flex-direction: column;
                        }
                        .container {
                            background-color: #ffffff;
                            border-radius: 8px;
                            box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                            padding: 30px;
                            width: 800px;
                            text-align: center;
                            overflow: auto;
                        }
                        h1 {
                            font-size: 24px;
                            color: #333;
                            margin-bottom: 20px;
                        }
                        form {
                            margin-top: 20px;
                        }
                        input[type="file"] {
                            padding: 10px;
                            border: 1px solid #ccc;
                            border-radius: 4px;
                            width: 100%;
                            margin-bottom: 20px;
                        }
                        input[type="submit"] {
                            background-color: #28a745;
                            color: white;
                            padding: 10px 20px;
                            border: none;
                            border-radius: 4px;
                            cursor: pointer;
                            font-size: 16px;
                            transition: background-color 0.3s ease;
                        }
                        input[type="submit"]:hover {
                            background-color: #218838;
                        }
                        .footer {
                            margin-top: 20px;
                            font-size: 12px;
                            color: #888;
                        }
                        .table-container {
                            margin-top: 20px;
                            text-align: left;
                            max-height: 300px;
                            overflow-y: scroll;
                            border: 1px solid #ddd;
                            padding: 10px;
                            background-color: #fff;
                            border-radius: 4px;
                            box-shadow: 0 2px 4px rgba(0, 0, 0, 0.1);
                        }
                        .table-container h2 {
                            text-align: center;
                            margin-bottom: 10px;
                        }
                        table {
                            width: 100%;
                            border-collapse: collapse;
                        }
                        table, th, td {
                            border: 1px solid #ddd;
                        }
                        th, td {
                            padding: 8px;
                            text-align: left;
                        }
                        th {
                            background-color: #f2f2f2;
                        }
                        /* Scrollbar customization */
                        .table-container::-webkit-scrollbar {
                            width: 8px;
                        }
                        .table-container::-webkit-scrollbar-thumb {
                            background-color: #888;
                            border-radius: 4px;
                        }
                        .table-container::-webkit-scrollbar-thumb:hover {
                            background-color: #555;
                        }
                    </style>
                </head>
                <body>
                    <div class="container">
                        <h1>Upload JSON File</h1>
                        <form method="POST" enctype="multipart/form-data">
                            <input type="file" name="file" required>
                            <input type="submit" value="Upload">
                        </form>
                        <div class="table-container">
                            <h2>Clients</h2>
                            {{ client_html | safe }}
                        </div>
                        <div class="table-container">
                            <h2>Locations</h2>
                            {{ location_html | safe }}
                        </div>
                        <div class="table-container">
                            <h2>Tasks</h2>
                            {{ task_html | safe }}
                        </div>
                    </div>
                </body>
                </html>
            ''', client_html=client_html, location_html=location_html, task_html=task_html)

    return '''
    <html>
    <head>
        <style>
            body {
                font-family: Arial, sans-serif;
                background-color: #f4f4f4;
                margin: 0;
                padding: 0;
                display: flex;
                justify-content: center;
                align-items: center;
                height: 100vh;
            }
            .container {
                background-color: #ffffff;
                border-radius: 8px;
                box-shadow: 0 4px 8px rgba(0, 0, 0, 0.1);
                padding: 30px;
                width: 400px;
                text-align: center;
            }
            h1 {
                font-size: 24px;
                color: #333;
                margin-bottom: 20px;
            }
            form {
                margin-top: 20px;
            }
            input[type="file"] {
                padding: 10px;
                border: 1px solid #ccc;
                border-radius: 4px;
                width: 100%;
                margin-bottom: 20px;
            }
            input[type="submit"] {
                background-color: #28a745;
                color: white;
                padding: 10px 20px;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 16px;
                transition: background-color 0.3s ease;
            }
            input[type="submit"]:hover {
                background-color: #218838;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Upload JSON File</h1>
            <form method="POST" enctype="multipart/form-data">
                <input type="file" name="file" required>
                <input type="submit" value="Upload">
            </form>
        </div>
    </body>
    </html>
    '''


if __name__ == '__main__':
    app.run(debug=True)