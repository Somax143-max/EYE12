"""
DRISHTI AI: Medical DICOM (.dcm) Fundus Handler (Item 51)
Provides:
- Ingestion of Ophthalmic Photography SOP Class (1.2.840.10008.5.1.4.1.1.77.1.5.1)
- Photometric Interpretation handling (RGB, MONOCHROME2, YBR_FULL, YBR_FULL_422)
- Window Center / Width rescale & 8-bit BGR normalization for PyTorch CNN
- Metadata extraction: PatientID, StudyDate, Modality, Manufacturer
- Exporting AI screening reports back as standard DICOM Secondary Capture
"""

import os, io
import cv2
import numpy as np
import pydicom
from pydicom.dataset import FileDataset, FileMetaDataset
from pydicom.uid import generate_uid, ExplicitVRLittleEndian

def read_dicom_file(filepath):
    """Reads a DICOM (.dcm) file and returns (is_valid, img_bgr, metadata, error)."""
    try:
        ds = pydicom.dcmread(filepath)
        return _process_dicom_dataset(ds, filepath=filepath)
    except Exception as e:
        return False, None, {}, f"DICOM parsing error: {str(e)}"

def read_dicom_bytes(raw_bytes):
    """Reads DICOM from in-memory byte buffer."""
    try:
        f = io.BytesIO(raw_bytes)
        ds = pydicom.dcmread(f)
        return _process_dicom_dataset(ds)
    except Exception as e:
        return False, None, {}, f"DICOM byte parsing error: {str(e)}"

def _process_dicom_dataset(ds, filepath=None):
    metadata = {
        "patient_id": getattr(ds, "PatientID", "ANONYMOUS"),
        "patient_name": str(getattr(ds, "PatientName", "Unknown")),
        "study_date": str(getattr(ds, "StudyDate", "N/A")),
        "modality": getattr(ds, "Modality", "OP"),
        "manufacturer": getattr(ds, "Manufacturer", "Generic Fundus Camera"),
        "photometric_interpretation": getattr(ds, "PhotometricInterpretation", "RGB"),
        "rows": getattr(ds, "Rows", 0),
        "columns": getattr(ds, "Columns", 0)
    }
    
    if not hasattr(ds, "pixel_array"):
        return False, None, metadata, "DICOM file contains no PixelData element."

    arr = ds.pixel_array
    photo = metadata["photometric_interpretation"]

    # Handle various photometric representations
    if photo in ["MONOCHROME1", "MONOCHROME2"]:
        # Normalize 12/16-bit to 8-bit
        arr = arr.astype(float)
        if photo == "MONOCHROME1":
            arr = np.max(arr) - arr # Invert
        p_min, p_max = np.min(arr), np.max(arr)
        if p_max > p_min:
            arr = ((arr - p_min) / (p_max - p_min) * 255.0).astype(np.uint8)
        else:
            arr = np.zeros(arr.shape, dtype=np.uint8)
        img_bgr = cv2.cvtColor(arr, cv2.COLOR_GRAY2BGR)

    elif photo == "RGB":
        img_bgr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_RGB2BGR)

    elif "YBR" in photo:
        # Convert YBR to RGB via pydicom color conversion
        try:
            from pydicom.pixel_data_handlers.util import convert_color_space
            rgb_arr = convert_color_space(arr, photo, "RGB")
            img_bgr = cv2.cvtColor(rgb_arr.astype(np.uint8), cv2.COLOR_RGB2BGR)
        except Exception:
            img_bgr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_RGB2BGR)
    else:
        # Default fallback
        if len(arr.shape) == 2:
            img_bgr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_GRAY2BGR)
        else:
            img_bgr = cv2.cvtColor(arr.astype(np.uint8), cv2.COLOR_RGB2BGR)

    h, w = img_bgr.shape[:2]
    metadata["width"] = w
    metadata["height"] = h
    if filepath:
        metadata["source_file"] = os.path.basename(filepath)

    return True, img_bgr, metadata, None

def export_as_dicom_secondary_capture(img_bgr, out_filepath, patient_id="PAT_001", study_desc="DRISHTI AI SCREENING REPORT"):
    """Exports an annotated fundus image or Grad-CAM overlay as standard DICOM file."""
    h, w = img_bgr.shape[:2]
    img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)

    file_meta = FileMetaDataset()
    file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.7" # Secondary Capture
    file_meta.MediaStorageSOPInstanceUID = generate_uid()
    file_meta.TransferSyntaxUID = ExplicitVRLittleEndian

    ds = FileDataset(out_filepath, {}, file_meta=file_meta, preamble=b"\0" * 128)
    ds.PatientName = f"Patient^{patient_id}"
    ds.PatientID = str(patient_id)
    ds.Modality = "OT" # Other
    ds.StudyDescription = study_desc
    ds.SeriesDescription = "DRISHTI AI Automated Analysis"
    ds.SOPClassUID = file_meta.MediaStorageSOPClassUID
    ds.SOPInstanceUID = file_meta.MediaStorageSOPInstanceUID

    ds.Rows = h
    ds.Columns = w
    ds.BitsAllocated = 8
    ds.BitsStored = 8
    ds.HighBit = 7
    ds.SamplesPerPixel = 3
    ds.PhotometricInterpretation = "RGB"
    ds.PlanarConfiguration = 0
    ds.PixelRepresentation = 0
    ds.PixelData = img_rgb.tobytes()

    ds.save_as(out_filepath)
    return True
