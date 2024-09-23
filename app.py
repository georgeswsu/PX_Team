from flask import Flask, request, jsonify, render_template
import os
import mysql.connector
from main import detect_rooms, analyze_floor_plan, match_rooms, get_image_size, store_rooms_to_mysql, \
    filter_detected_rooms_by_probability
from test15 import parse_tasks, parse_client, parse_location, insert_clients_into_sql, get_table_index, \
    analyze_pdf_with_azure, get_json_from_azure_result

app = Flask(__name__)

# MySQL configuration
mysql_host = "localhost"
mysql_user = "root"
mysql_password = "85982480hy"
mysql_database = "pxtest"

# Upload folder
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Database connection function
def create_db_connection():
    return mysql.connector.connect(
        host=mysql_host,
        user=mysql_user,
        password=mysql_password,
        database=mysql_database
    )

# creat tables
def create_tables(conn):
    cursor = conn.cursor()

    # creat client table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS client (
            id INT AUTO_INCREMENT PRIMARY KEY,
            name VARCHAR(255),
            site VARCHAR(255)
        )
    ''')
    conn.commit()

    # create location table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS location (
            id INT AUTO_INCREMENT PRIMARY KEY,
            location VARCHAR(255),
            client INT,
            FOREIGN KEY (client) REFERENCES client(id)
        )
    ''')
    conn.commit()

    # create task table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS task (
            id INT AUTO_INCREMENT PRIMARY KEY,
            location INT,
            description VARCHAR(255),
            monday VARCHAR(255),
            tuesday VARCHAR(255),
            wednesday VARCHAR(255),
            thursday VARCHAR(255),
            friday VARCHAR(255),
            saturday VARCHAR(255),
            sunday VARCHAR(255),
            FOREIGN KEY (location) REFERENCES location(id)
        )
    ''')
    conn.commit()

    # create rooms table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS rooms (
            id INT AUTO_INCREMENT PRIMARY KEY,
            area VARCHAR(255),
            room_name VARCHAR(255),
            room_size VARCHAR(255)
        )
    ''')
    conn.commit()

# Route for rendering the HTML upload page
@app.route('/')
def index():
    return render_template('index.html')

# Route for Upload files
@app.route('/upload', methods=['POST'])
def upload_files():
    scope_files = request.files.getlist('jsonFiles')
    floor_plan_files = request.files.getlist('floorPlanFiles')
    area_names = request.form.getlist('areaNames[]')

    if not scope_files and not floor_plan_files:
        return jsonify({'error': 'Please upload at least one Scope of Work File or Floor Plan file'}), 400

    results = {
        'jsonResults': [],
        'floorPlanResults': []
    }

    conn = create_db_connection()

    # Handover json file
    if scope_files:
        for file in scope_files:
            try:
                file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
                file.save(file_path)

                json_data = analyze_pdf_with_azure(file_path)
                data_json = get_json_from_azure_result(json_data)

                # phase and insert client data
                client_data_frame = parse_client(data_json)
                insert_clients_into_sql('client', client_data_frame, conn)
                client_index_map = get_table_index('client', 'id', 'name', conn)

                # phase and insert location data
                location_data_frame = parse_location(data_json, client_index_map)
                insert_clients_into_sql('location', location_data_frame, conn)
                location_index_map = get_table_index('location', 'id', 'location', conn)

                # phase and insert task data
                task_data_frame = parse_tasks(data_json, location_index_map)
                insert_clients_into_sql('task', task_data_frame, conn)

                results['jsonResults'].append({
                    'filename': file.filename,
                    'client_data': client_data_frame.to_html(classes='table table-striped', index=False),
                    'location_data': location_data_frame.to_html(classes='table table-striped', index=False),
                    'task_data': task_data_frame.to_html(classes='table table-striped', index=False)
                })
            except Exception as e:
                results['jsonResults'].append({
                    'filename': file.filename,
                    'error': str(e)
                })

    # Handover floor plan file
    if floor_plan_files:
        for file, area_name in zip(floor_plan_files, area_names):
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(file_path)

            image_width, image_height = get_image_size(file_path)
            detected_rooms = filter_detected_rooms_by_probability(detect_rooms(file_path))
            extracted_rooms = analyze_floor_plan(file_path)
            matched_rooms = match_rooms(detected_rooms, extracted_rooms, image_width, image_height)

            # phase and insert room data
            for room in matched_rooms:
                room['room_tag'] = area_name if area_name else file.filename
            store_rooms_to_mysql(matched_rooms)

            results['floorPlanResults'].append({
                'filename': file.filename,
                'area': area_name,
                'matched_rooms': matched_rooms
            })

    conn.close()

    print('Results being sent to the front-end:', results)
    return jsonify({'results': results})

# Run the app
if __name__ == '__main__':
    conn = create_db_connection()
    create_tables(conn)
    conn.close()
    app.run(debug=True)