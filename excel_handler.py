from typing import List, Tuple
import pandas as pd
import openpyxl

class ExcelHandler:
    _current_df: pd.DataFrame = None
    _student_id_col_name: str = ""

    @classmethod
    def load_photographed_students(cls, file_path: str) -> Tuple[List[str], str]:
        """
        Reads Excel (.xlsx, .xls) or CSV (.csv) files, preserves leading zeros for student IDs,
        matches studentId and status columns case-insensitively, filters status == "PHOTOGRAPHED",
        and removes duplicates while maintaining order.
        Returns (list_of_student_ids, error_message).
        """
        try:
            is_csv = file_path.lower().endswith('.csv')
            
            if is_csv:
                df_headers = pd.read_csv(file_path, nrows=1)
            else:
                excel_file = pd.ExcelFile(file_path)
                sheet_name = excel_file.sheet_names[0]
                df_headers = pd.read_excel(file_path, sheet_name=sheet_name, nrows=1)
            
            student_id_col = None
            first_name_col = None
            last_name_col = None
            grade_col = None
            status_col = None
            
            for col in df_headers.columns:
                col_clean = str(col).strip().lower().replace(' ', '').replace('_', '')
                if col_clean in ['studentid', 'student', 'id']:
                    student_id_col = col
                elif col_clean in ['firstname', 'first']:
                    first_name_col = col
                elif col_clean in ['lastname', 'last']:
                    last_name_col = col
                elif col_clean in ['grade', 'gr']:
                    grade_col = col
                elif col_clean == 'status':
                    status_col = col
            
            if not student_id_col:
                return [], f"Missing required column 'studentId' in file."

            dtypes = {student_id_col: str}
            if first_name_col: dtypes[first_name_col] = str
            if last_name_col: dtypes[last_name_col] = str
            if grade_col: dtypes[grade_col] = str

            # Read whole sheet/file ensuring studentId column is read strictly as string
            if is_csv:
                df = pd.read_csv(file_path, dtype=dtypes)
            else:
                df = pd.read_excel(
                    file_path, 
                    sheet_name=sheet_name, 
                    dtype=dtypes
                )

            cls._current_df = df.copy()
            cls._student_id_col_name = student_id_col

            # Filter rows where status is PHOTOGRAPHED (or include all if status column absent)
            photographed_items = []
            for _, row in df.iterrows():
                raw_id = row[student_id_col]
                raw_status = row[status_col] if status_col else "PHOTOGRAPHED"

                if pd.isna(raw_id) or (status_col and pd.isna(raw_status)):
                    continue

                status_str = str(raw_status).strip().upper() if status_col else "PHOTOGRAPHED"
                if status_str == "PHOTOGRAPHED":
                    clean_id = str(raw_id).strip()
                    if clean_id.endswith('.0'):
                        clean_id = clean_id[:-2]
                    
                    if clean_id:
                        fn = str(row[first_name_col]).strip() if first_name_col and not pd.isna(row[first_name_col]) else ""
                        ln = str(row[last_name_col]).strip() if last_name_col and not pd.isna(row[last_name_col]) else ""
                        gr = str(row[grade_col]).strip() if grade_col and not pd.isna(row[grade_col]) else ""

                        name_part = f"{fn} {ln}".strip()
                        meta_str = clean_id
                        if name_part:
                            meta_str += f" | {name_part}"
                        if gr:
                            meta_str += f" | Gr: {gr}"

                        photographed_items.append({
                            'id': clean_id,
                            'first_name': fn,
                            'last_name': ln,
                            'grade': gr,
                            'meta_str': meta_str
                        })

            # Remove duplicates preserving order
            seen = set()
            unique_items = []
            for item in photographed_items:
                cid = item['id']
                if cid not in seen:
                    seen.add(cid)
                    unique_items.append(item)

            if not unique_items:
                return [], "No rows found matching status = 'PHOTOGRAPHED'."

            return unique_items, ""

        except Exception as e:
            return [], f"Error processing Excel file: {str(e)}"

    @classmethod
    def export_remaining_students(cls, remaining_ids: List[str], export_path: str, remaining_records: List[dict] = None) -> Tuple[bool, str]:
        """
        Exports all original columns and rows from the loaded spreadsheet matching
        the remaining unprinted student IDs to a CSV or Excel file.
        """
        try:
            if not remaining_ids:
                return False, "No remaining student IDs provided."

            rows_to_export = []

            # If we have a cached original DataFrame and the student ID column exists
            if cls._current_df is not None and cls._student_id_col_name in cls._current_df.columns:
                id_col = cls._student_id_col_name
                
                # Build lookup mapping clean student ID -> list of row dicts from _current_df
                # Preserving all original columns
                df_dict = cls._current_df.to_dict('records')
                id_to_rows = {}
                for row in df_dict:
                    val = row.get(id_col, '')
                    if pd.isna(val):
                        continue
                    clean_id = str(val).strip()
                    if clean_id.endswith('.0'):
                        clean_id = clean_id[:-2]
                    if clean_id:
                        if clean_id not in id_to_rows:
                            id_to_rows[clean_id] = []
                        id_to_rows[clean_id].append(row)

                # Build record lookup from remaining_records if provided
                rec_dict = {}
                if remaining_records:
                    for rec in remaining_records:
                        rid = rec.get('id', '')
                        if rid:
                            rec_dict[rid] = rec

                for sid in remaining_ids:
                    clean_sid = str(sid).strip()
                    if clean_sid.endswith('.0'):
                        clean_sid = clean_sid[:-2]

                    if clean_sid in id_to_rows and id_to_rows[clean_sid]:
                        # Take matching original row to preserve all original columns
                        rows_to_export.append(dict(id_to_rows[clean_sid].pop(0)))
                    elif clean_sid in rec_dict:
                        rec = rec_dict[clean_sid]
                        rows_to_export.append({
                            id_col: clean_sid,
                            'firstName': rec.get('first_name', ''),
                            'lastName': rec.get('last_name', ''),
                            'grade': rec.get('grade', ''),
                            'status': 'PHOTOGRAPHED'
                        })
                    else:
                        rows_to_export.append({
                            id_col: clean_sid,
                            'status': 'PHOTOGRAPHED'
                        })
            else:
                # Fallback when _current_df is None
                rec_dict = {}
                if remaining_records:
                    for rec in remaining_records:
                        rid = rec.get('id', '')
                        if rid:
                            rec_dict[rid] = rec

                for sid in remaining_ids:
                    clean_sid = str(sid).strip()
                    if clean_sid.endswith('.0'):
                        clean_sid = clean_sid[:-2]
                    if clean_sid in rec_dict:
                        rec = rec_dict[clean_sid]
                        rows_to_export.append({
                            'studentId': clean_sid,
                            'firstName': rec.get('first_name', ''),
                            'lastName': rec.get('last_name', ''),
                            'grade': rec.get('grade', ''),
                            'status': 'PHOTOGRAPHED'
                        })
                    else:
                        rows_to_export.append({
                            'studentId': clean_sid,
                            'status': 'PHOTOGRAPHED'
                        })

            df_export = pd.DataFrame(rows_to_export)

            if export_path.lower().endswith('.csv'):
                df_export.to_csv(export_path, index=False)
            else:
                df_export.to_excel(export_path, index=False)

            return True, f"Successfully saved {len(df_export)} remaining student record(s) to {export_path}"
        except Exception as e:
            return False, f"Error saving remaining student records: {str(e)}"

    @classmethod
    def load_student_list(cls, file_path: str) -> Tuple[List[dict], str]:
        """
        Loads student list from a saved CSV or Excel file (which has all columns).
        """
        return cls.load_photographed_students(file_path)

    @classmethod
    def load_sync_zip(cls, zip_path: str) -> Tuple[List[dict], str]:
        """
        Reads a sync .zip file containing index.json, idCards, and Photos.
        Parses index.json to find students who HAVE photos (photos array is not empty).
        Returns (list_of_records, error_message).
        """
        import zipfile
        import json

        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                json_filename = None
                for fname in zf.namelist():
                    if fname.lower() == 'index.json' or fname.lower().endswith('/index.json'):
                        json_filename = fname
                        break

                if not json_filename:
                    return [], "Missing 'index.json' file inside the zip archive."

                with zf.open(json_filename) as f:
                    data = json.load(f)

            students = []
            photos_set = set()

            if isinstance(data, dict):
                students = data.get('students', data.get('Students', []))
                raw_photos = data.get('photos', data.get('Photos', data.get('studentPhotos', data.get('student_photos', []))))
                
                # Collect all photo student IDs into photos_set
                if isinstance(raw_photos, list):
                    for item in raw_photos:
                        if isinstance(item, dict):
                            p_id = item.get('studentId', item.get('student_id', item.get('id', item.get('StudentId', ''))))
                        else:
                            p_id = str(item)
                        if p_id:
                            clean_p_id = str(p_id).strip()
                            if clean_p_id.endswith('.0'):
                                clean_p_id = clean_p_id[:-2]
                            photos_set.add(clean_p_id)
            elif isinstance(data, list):
                students = data

            photographed_items = []
            seen = set()

            for s in students:
                if not isinstance(s, dict):
                    continue

                raw_id = s.get('studentId', s.get('student_id', s.get('id', s.get('StudentId', ''))))
                if not raw_id:
                    continue

                clean_id = str(raw_id).strip()
                if clean_id.endswith('.0'):
                    clean_id = clean_id[:-2]

                if not clean_id:
                    continue

                # Check if this student HAS a photo in the photos array
                student_has_photo = clean_id in photos_set

                # Also check student-level photo array / object / path if present
                if not student_has_photo:
                    s_photos = s.get('photos', s.get('Photos', s.get('studentPhotos', None)))
                    if isinstance(s_photos, list) and len(s_photos) > 0:
                        student_has_photo = True
                    else:
                        s_photo = s.get('photo', s.get('photoPath', s.get('hasPhoto', None)))
                        if s_photo is True or (isinstance(s_photo, str) and s_photo.strip()):
                            student_has_photo = True

                # Include ONLY students that HAVE photographs
                if student_has_photo:
                    if clean_id not in seen:
                        seen.add(clean_id)
                        fn = str(s.get('firstName', s.get('first_name', s.get('FirstName', '')))).strip()
                        ln = str(s.get('lastName', s.get('last_name', s.get('LastName', '')))).strip()
                        gr = str(s.get('grade', s.get('Grade', ''))).strip()

                        name_part = f"{fn} {ln}".strip()
                        meta_str = clean_id
                        if name_part:
                            meta_str += f" | {name_part}"
                        if gr:
                            meta_str += f" | Gr: {gr}"

                        photographed_items.append({
                            'id': clean_id,
                            'first_name': fn,
                            'last_name': ln,
                            'grade': gr,
                            'meta_str': meta_str
                        })

            if not photographed_items:
                return [], "No photographed students found (photos array is empty in index.json)."

            # Update _current_df for sync zip load
            df_sync = pd.DataFrame([
                {
                    'studentId': item['id'],
                    'firstName': item['first_name'],
                    'lastName': item['last_name'],
                    'grade': item['grade'],
                    'status': 'PHOTOGRAPHED'
                } for item in photographed_items
            ])
            cls._current_df = df_sync
            cls._student_id_col_name = 'studentId'

            return photographed_items, ""

        except Exception as e:
            return [], f"Error reading Sync Zip file: {str(e)}"

