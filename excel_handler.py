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
            status_col = None
            
            for col in df_headers.columns:
                col_clean = str(col).strip().lower().replace(' ', '').replace('_', '')
                if col_clean in ['studentid', 'student', 'id']:
                    student_id_col = col
                elif col_clean == 'status':
                    status_col = col
            
            if not student_id_col:
                return [], f"Missing required column 'studentId' in file."
            if not status_col:
                return [], f"Missing required column 'status' in file."

            # Read whole sheet/file ensuring studentId column is read strictly as string
            if is_csv:
                df = pd.read_csv(file_path, dtype={student_id_col: str})
            else:
                df = pd.read_excel(
                    file_path, 
                    sheet_name=sheet_name, 
                    dtype={student_id_col: str}
                )

            cls._current_df = df.copy()
            cls._student_id_col_name = student_id_col

            # Filter rows where status is PHOTOGRAPHED
            photographed_ids = []
            for _, row in df.iterrows():
                raw_id = row[student_id_col]
                raw_status = row[status_col]

                if pd.isna(raw_id) or pd.isna(raw_status):
                    continue

                status_str = str(raw_status).strip().upper()
                if status_str == "PHOTOGRAPHED":
                    clean_id = str(raw_id).strip()
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

    @classmethod
    def export_remaining_students(cls, remaining_ids: List[str], export_path: str) -> Tuple[bool, str]:
        """
        Exports all original columns and rows from the loaded spreadsheet matching
        the remaining unprinted student IDs to a CSV or Excel file.
        """
        try:
            if cls._current_df is None or cls._student_id_col_name not in cls._current_df.columns:
                # Fallback if no full original dataframe is cached
                df_export = pd.DataFrame({"studentId": [str(sid) for sid in remaining_ids]})
            else:
                # Convert student ID column to string to match remaining_ids
                id_col = cls._student_id_col_name
                temp_series = cls._current_df[id_col].astype(str).str.strip().str.replace(r'\.0$', '', regex=True)
                
                # Filter original dataframe preserving all original columns
                rem_set = set(remaining_ids)
                mask = temp_series.isin(rem_set)
                df_export = cls._current_df[mask].copy()

            if export_path.endswith('.csv'):
                df_export.to_csv(export_path, index=False)
            else:
                df_export.to_excel(export_path, index=False)
            return True, f"Successfully saved {len(df_export)} remaining student record(s) with all columns to {export_path}"
        except Exception as e:
            return False, f"Error saving remaining student records: {str(e)}"

    @classmethod
    def load_student_list(cls, file_path: str) -> Tuple[List[str], str]:
        """
        Loads student list from a saved CSV or Excel file (which has all columns).
        """
        return cls.load_photographed_students(file_path)
