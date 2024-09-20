import os
import json
import pandas as pd
import mysql.connector

from flask import Flask, request, redirect, jsonify, render_template

# Initialize the Flask application
app = Flask(__name__)
UPLOAD_FOLDER = 'uploads/'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# Create the upload folder if it doesn't exist
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)


def get_json(filename):
    with open(filename) as file:
        json_file = json.load(file)
    return json_file['analyzeResult']['tables']


def parse_client(json_file):
    table = json_file[0]
    row_count = table['rowCount']
    column_count = table['columnCount']

    df = pd.DataFrame(index=range(column_count - 1), columns=range(row_count + 1))

    for cell in table['cells']:
        row_index = cell.get('rowIndex')
        column_index = cell.get('columnIndex')
        content = cell.get('content')
        if column_index != 0:
            df.iloc[column_index - 1, row_index + 1] = content

    df.columns = ['client_id', 'client_name', 'client_site']

    return add_index(df)


def add_index(data_frame):
    i = 0
    for row in data_frame.iterrows():
        data_frame.iloc[i, 0] = i + 1
        i += 1
    return data_frame


def parse_location(json_file, client_index_map):
    data_frame = pd.DataFrame(index=range(len(json_file) - 1), columns=range(3))

    for i in range(1, len(json_file)):
        table = json_file[i]
        data_frame.iloc[i - 1, 1] = get_location_from_table(table)
        data_frame.iloc[i - 1, 2] = client_index_map['ABC Company']

    data_frame.columns = ['location_id', 'location_address', 'client']

    return add_index(data_frame)


def parse_tasks(json_file, location_index_map):
    task_number = 0
    # get the overall number of tasks
    for i in range(1, len(json_file)):
        table = json_file[i]
        task_number += table['rowCount'] - 1

    task_number += 1

    data_frame = pd.DataFrame(index=range(task_number - 1), columns=range(10))

    task_row_grap = 0
    for i in range(1, len(json_file)):
        table = json_file[i]

        for cell in table['cells']:
            row_index = cell.get('rowIndex')
            column_index = cell.get('columnIndex')
            content = cell.get('content')

            location = get_location_from_table(table)

            if row_index != 0:
                data_frame.iloc[row_index + task_row_grap - 1, 1] = location_index_map[location]
                data_frame.iloc[row_index + task_row_grap - 1, column_index + 2] = content

        task_row_grap += table['rowCount'] - 1

    data_frame.columns = ['task_id', 'location_id', 'description', 'monday', 'tuesday',
                          'wednesday', 'thursday', 'friday', 'saturday', 'sunday']

    return add_index(data_frame)


def get_location_from_table(table):
    cells = table['cells']

    for cell in cells:
        if cell.get('rowIndex') == 0 and cell.get('columnIndex') == 0:
            return cell.get('content')
    return "unknown"


def create_index_map(data_frame, index_col, key_col):
    index_map = {}
    i = 0

    for row in data_frame.iterrows():
        index = data_frame[index_col][i]
        value = data_frame[key_col][i]
        index_map[value] = index
        i += 1
    return index_map


def insert_into_sql(table_name, data_frame, conn):
    cursor = conn.cursor()
    placeholders = ', '.join(['%s'] * len(data_frame.columns))
    columns = ', '.join(data_frame.columns)
    sql = f"INSERT INTO {table_name} ({columns}) VALUES ({placeholders})"
    cursor.executemany(sql, data_frame.values.tolist())
    conn.commit()


@app.route('/', methods=['GET', 'POST'])
def upload_file():
    if request.method == 'POST':
        if 'file' not in request.files:
            return redirect(request.url)  # Redirect if no file part in the request

        file = request.files['file']

        if file.filename == '':
            return redirect(request.url)  # Redirect if no selected file

        if file and file.filename.endswith('.json'):
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], file.filename)
            file.save(filepath)
            data_json = get_json(filepath)

            client_data_frame = parse_client(data_json)
            client_index_map = create_index_map(client_data_frame, 'client_id', 'client_name')

            location_data_frame = parse_location(data_json, client_index_map)
            location_index_map = create_index_map(location_data_frame, 'location_id', 'location_address')

            task_data_frame = parse_tasks(data_json, location_index_map)

            #Excel stuff
            # output_filename = 'test_sheet.xlsx'
            # with pd.ExcelWriter(output_filename, engine='openpyxl') as writer:
            #     client_data_frame.to_excel(writer, sheet_name='clients', index=False)
            #     location_data_frame.to_excel(writer, sheet_name='locations', index=False)
            #     task_data_frame.to_excel(writer, sheet_name='tasks', index=False)

            # Connect to MySQL database and insert data
            try:
                conn = mysql.connector.connect(
                    host="localhost",
                    database="test_db5",
                    user="root",
                    password="root"
                )

                # Insert data into MySQL tables
                insert_into_sql('client', client_data_frame, conn)
                insert_into_sql('location', location_data_frame, conn)
                insert_into_sql('task', task_data_frame, conn)

            finally:
                conn.close()

            # Send the generated Excel file
            #return send_file(output_filename, as_attachment=True)

        else:
            # Return a message if the file is not a JSON file
            return "Please upload a valid JSON file.", 400

    # If the request method is GET, show the upload form
    return render_template('Main_page.html')




# API STUFF
#Get all clients
@app.route('/clients', methods=['GET'])
def get_clients():
    try:
        conn = mysql.connector.connect(
            host="localhost",
            database="test_db5",
            user="root",
            password="root"
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM client")
        result = cursor.fetchall()

        print(result)

        # Returning the result as JSON
        return render_template('clients.html', clients=result)
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        conn.close()


#search for client based on the client id
@app.route('/clients/<int:client_id>', methods=['GET'])
def get_client(client_id):
    try:
        conn = mysql.connector.connect(
            host="localhost",
            database="test_db5",
            user="root",
            password="root"
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM client WHERE client_id = %s", (client_id,))
        result = cursor.fetchone()


        if result:
            return render_template('clients.html', clients=result)
        else:
            return jsonify({"message": "Client not found"}), 404
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        conn.close()


#Get all locations
@app.route('/location', methods=['GET'])
def get_locations():
    try:
        conn = mysql.connector.connect(
            host="localhost",
            database="test_db5",
            user="root",
            password="root"
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM location")
        result = cursor.fetchall()

        # Print result for debugging
        print(result)

        # Render the HTML template with the list of locations
        return render_template('locations.html', locations=result)
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        conn.close()


#search for location based on client id
@app.route('/location/<int:client_id>', methods=['GET'])
def get_location(client_id):
    try:
        conn = mysql.connector.connect(
            host="localhost",
            database="test_db5",
            user="root",
            password="root"
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM location WHERE client = %s", (client_id,))
        result = cursor.fetchall()


        if result:
            return render_template('locations.html', locations=result)
        else:
            return jsonify({"message": "Location not found"}), 404
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        conn.close()


#get all tasks
@app.route('/task', methods=['GET'])
def get_tasks():
    try:
        conn = mysql.connector.connect(
            host="localhost",
            database="test_db5",
            user="root",
            password="root"
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM task")
        result = cursor.fetchall()

        print(result)
        # Returning the result as JSON
        return render_template('tasks.html', tasks=result)
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        conn.close()

#search for tasks based on location id
@app.route('/task/<int:location_id>', methods=['GET'])
def get_task(location_id):
    try:
        conn = mysql.connector.connect(
            host="localhost",
            database="test_db5",
            user="root",
            password="root"
        )
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM task WHERE location_id = %s", (location_id,))
        result = cursor.fetchall()

        if result:
            return render_template('tasks.html', tasks=result)
        else:
            return jsonify({"message": "Task not found"}), 404
    except mysql.connector.Error as err:
        return jsonify({"error": str(err)}), 500
    finally:
        conn.close()









if __name__ == '__main__':
    app.run(debug=True)

# SQL DATABASE
# CREATE TABLE client (
#     client_id INT NOT NULL AUTO_INCREMENT,
#     client_name CHAR(50) NOT NULL,
#     client_site CHAR(50) NOT NULL,
#     PRIMARY KEY (client_id)
# );
#
# -- Create the location table with a foreign key referencing client
# CREATE TABLE location (
#     location_id INT NOT NULL,
#     location_address CHAR(50) NOT NULL,
#     client INT NOT NULL,
#     PRIMARY KEY (location_id),
#     CONSTRAINT location_fk FOREIGN KEY (client) REFERENCES client(client_id)
# );
#
# -- Create the task table with a foreign key referencing location
# CREATE TABLE task (
#     task_id INT NOT NULL,
#     location_id INT NOT NULL,
#     description CHAR(200) NOT NULL,
#     monday CHAR(50) NOT NULL,
#     tuesday CHAR(50) NOT NULL,
#     wednesday CHAR(50) NOT NULL,
#     thursday CHAR(50) NOT NULL,
#     friday CHAR(50) NOT NULL,
#     saturday CHAR(50) NOT NULL,
#     sunday CHAR(50) NOT NULL,
#     PRIMARY KEY (task_id),
#     CONSTRAINT task_fk FOREIGN KEY (location_id) REFERENCES location(location_id)
# );
#
# SELECT * FROM client;
# SELECT * FROM location;
# SELECT * FROM task;