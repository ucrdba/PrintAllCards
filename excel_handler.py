from typing import List, Tuple
import pandas as pd
import openpyxl

class ExcelHandler:
    @staticmethod
    def load_photographed_students(file_path: str) -> Tuple[List[str], str]:
        """
        Reads Excel file (.xlsx, .xls), preserves leading zeros for student IDs,
        matches studentId and status columns case-insensitively, filters status == "PHOTOGRAPHED",
        and removes duplicates while maintaining order.
        Returns (list_of_student_ids, error_message).
        """
        try:
            # First load column names using pandas/openpyxl
            excel_file = pd.ExcelFile(file_path)
            sheet_name = excel_file.sheet_names[0]
            
            # Read first row to inspect headers case-insensitively
            df_headers = pd.read_excel(file_path, sheet_name=sheet_name, nrows=1)
            
            student_id_col = None
            status_col = None
            
            for col in df_headers.columns:
                col_clean = str(col).strip().lower().replace(' ', '').replace('_', '')
                if col_clean == 'studentid':
                    student_id_col = col
                elif col_clean == 'status':
                    status_col = col
            
            if not student_id_col:
                return [], f"Missing required column 'studentId' in spreadsheet."
            if not status_col:
                return [], f"Missing required column 'status' in spreadsheet."

            # Read whole sheet ensuring studentId column is read strictly as string to preserve leading zeros
            df = pd.read_excel(
                file_path, 
                sheet_name=sheet_name, 
                dtype={student_id_col: str}
            )

            # Filter rows where status is PHOTOGRAPHED (case-insensitive, trimmed)
            photographed_ids = []
            for _, row in df.iterrows():
                raw_id = row[student_id_col]
                raw_status = row[status_col]

                if pd.isna(raw_id) or pd.isna(raw_status):
                    continue

                status_str = str(raw_status).strip().upper()
                if status_str == "PHOTOGRAPHED":
                    # Convert to string and strip whitespace, but do NOT convert to int (preserve '001234')
                    clean_id = str(raw_id).strip()
                    # Handle if pandas rendered '1234.0' for floats
                    if clean_id.endswith('.0'):
                        clean_id = clean_id[:-2]
                    
                    if clean_id:
                        photographed_ids.append(clean_id)

            # Remove duplicates preserving order
            seen = set()
            unique_ids = []
            for sid in photographed_ids:
                if sid not in seen:
                    seen.add(sid)
                    unique_ids.append(sid)

            if not unique_ids:
                return [], "No rows found matching status = 'PHOTOGRAPHED'."

            return unique_ids, ""

        except Exception as e:
            return [], f"Error processing Excel file: {str(e)}"
