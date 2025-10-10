import os,sys,logging,base64
import pandas as pd
import json
from pathlib import Path

# class file imports 
sys.path.append(str(Path(__file__).resolve().parents[2]))
from src.api.SaviyntAPI import SaviyntAPI
from src.api.ServicenowAPI import ServicenowAPI

# Logger Setup
logger = logging.getLogger("ExtractFile")  # Use named logger



def getApplicationInfo(excel_path):
    # Read Excel without headers
    df = pd.read_excel(excel_path, sheet_name="1. Application information", header=None)
    
    # Keys: B8:B11 → index 1, rows 8-11 → 7:11
    keys = df.iloc[7:11, 1].astype(str).str.strip()
    
    # Values: C8:C11 → index 2, rows 8-11 → 7:11
    values = df.iloc[7:11, 2].astype(str).str.strip()
    
    # Convert to dictionary and then JSON
    data_dict = dict(zip(keys, values))
    
    return json.dumps(data_dict, indent=4)

def getADGroupsasJSON(excel_path):
    df = pd.read_excel(excel_path, sheet_name="2.a. AD Groups", header=7)

    # Drop "Unnamed" columns (Excel index leftovers)
    df = df.loc[:, ~df.columns.str.contains("^Unnamed")]

    # Replace NaN with None (→ null in JSON)
    df = df.where(pd.notna(df), None)

    # Convert to JSON
    json_data = df.to_json(orient="records", indent=4)

    return json_data

def getUserProvisioningApproach(excel_path):
    # Read Excel with all columns
    df = pd.read_excel(excel_path, sheet_name="2. User provisioning approach", header=None)

    # Row 8 in Excel = index 7 in pandas
    row = df.iloc[7]

    # Column 3 (index 2) = key, Column 4 (index 3) = value
    key = str(row[2]).strip()
    value = row[3]

    # Build dictionary
    data_dict = {key: value}

    return json.dumps(data_dict, indent=4)

def getUserTypeLandscape(excel_path):
    # read whole sheet without headers
    df = pd.read_excel(excel_path, sheet_name="3. User type landscape", header=None)

    # Heading is at C5(row=4, col=2, 0-based indexing)
    heading = df.iloc[4,2]

    #Options are C6:C11 (row=5-10, col=2)
    options = df.iloc[5:11,2].tolist()

    #Values are D6:D11 (row=5-10, col=3)
    values = df.iloc[5:11, 3].to_list()

    #Build dict
    data_dict = {opt: (str(val) if "other" in opt.lower() else bool(val)) for opt, val in zip(options, values)}

    return json.dumps({heading:data_dict}, indent=4)

def getAccessRequestApproval(excel_path):
    # Read Excel without headers
    df = pd.read_excel(excel_path, sheet_name="4. Access request approval", header=None)
    
    # Row 5 (index 4), Column C (index 2) = main heading
    main_key = str(df.iloc[4, 2]).strip()
    
    # Rows 6-8 (indexes 5,6,7), Column C (2) = options
    options = df.iloc[5:8, 2].astype(str).str.strip().tolist()
    
    # Rows 6-8 (indexes 5,6,7), Column D (3) = checkboxes
    checkboxes = df.iloc[5:8, 3].tolist()
    
    # Tick values (adjust if your Excel stores differently)
    ticked_values = [True, "TRUE", "True", "true", 1, "1", "X", "x", "Yes", "yes"]

    # Get the first selected option
    selected_value = None
    for opt, cb in zip(options, checkboxes):
        if cb in ticked_values:
            selected_value = opt
            break

    data_dict = {main_key: selected_value if selected_value else ""}
    
    return json.dumps(data_dict, indent=4)

def getUserExperience(excel_path):
    # Read Excel without headers
    df = pd.read_excel(excel_path, sheet_name="5. User experience", header=None)  

    # Specify the rows that contain key-value pairs
    key_rows = [5, 7, 9, 11]  # Excel row numbers 6,8,10,12 → zero-based index

    data_dict = {}
    for row in key_rows:
        key = str(df.iloc[row, 2]).strip()   # Column C → index 2
        value = str(df.iloc[row, 3]).strip() # Column D → index 3
        data_dict[key] = value

    return json.dumps(data_dict, indent=4)

def getExcelRoles(excel_path):

    user_authorization_sheet = pd.read_excel(excel_path, sheet_name="3.a. User authorization matrix", header=2)
    pd.set_option("display.max_columns", None)
    headers = user_authorization_sheet.iloc[0]
    headers = [h for h in headers if pd.notna(h) and str(h).strip().lower() != "roles"]
    
    return headers



if __name__=="__main__":
    repo_root = Path(__file__).resolve().parents[2]
    artifacts_dir = repo_root / "artifacts"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    
    base64file = os.environ.get("FILE") # Use this line if FILE is set as an env var
    excel_bytes = base64.b64decode(base64file)

    # # Save to disk
    out_path = artifacts_dir / "master.xlsx"
    out_path.write_bytes(excel_bytes)

    final_json_data = {
        "ApplicationInformation": json.loads(getApplicationInfo(out_path)),
        "AllADGroupsInformation": json.loads(getADGroupsasJSON(out_path)),
        "UserProvisioningApproach": json.loads(getUserProvisioningApproach(out_path)),
        "UserTypeLandscape": json.loads(getUserTypeLandscape(out_path)),
        "AccessRequestApproval": json.loads(getAccessRequestApproval(out_path)),
        "UserExperience": json.loads(getUserExperience(out_path)),
        "Roles": getExcelRoles(out_path)
    }

    # Save the final JSON file
    json_path = artifacts_dir / "ExtractedData.json"
    with open(json_path, "w") as f:
        json.dump(final_json_data, f, indent=4)

    logger.info(f"JSON file for Excel is created at {json_path}")
    print(json.dumps(final_json_data, indent=4))










