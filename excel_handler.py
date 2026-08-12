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
            if not status_col:
                return [], f"Missing required column 'status' in file."

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

            # Filter rows where status is PHOTOGRAPHED
            photographed_items = []
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
                        fn = str(row[first_name_col]).strip() if first_name_col and not pd.isna(row[first_name_col]) else ""
                        ln = str(row[last_name_col]).strip() if last_name_col and not pd.isna(row[last_name_col]) else ""
                        gr = str(row[grade_col]).strip() if grade_col and not pd.isna(row[grade_col]) else ""

                        name_part = f"{fn} {ln}".strip()
                        meta_str = clean_id
                        if name_part:
                            meta_str += f" | {name_part}"
                        if gr:
                            meta_str += f" | Gr: {gr}"

                        photographed_items.append((clean_id, meta_str))

            # Remove duplicates preserving order
            seen = set()
            unique_items = []
            for clean_id, meta_str in photographed_items:
                if clean_id not in seen:
                    seen.add(clean_id)
                    unique_items.append((clean_id, meta_str))

            if not unique_items:
                return [], "No rows found matching status = 'PHOTOGRAPHED'."

            return unique_items, ""

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
