import os
import xml.etree.ElementTree as ET
from typing import Dict, Any

from potentiostat.parsing.sequence_config import OCPConfig, EISConfig, LPRConfig, CPPConfig, SequenceConfig

def parse_element_params(element) -> Dict[str, Any]:
    raw_data = {}
    
    name_el = element.find("name")
    if name_el is not None:
        raw_data["title"] = name_el.text

    parameters = element.find("parameters")
    if parameters is None:
        return raw_data
        
    for child in parameters:
        tag = child.attrib.get("tag")
        if not tag:
            continue
            
        if child.tag == "explain_poten":
            raw_data[tag] = {
                "value": child.attrib.get("value"),
                "versus": child.attrib.get("versus")
            }
        elif "value" in child.attrib:
            val = child.attrib["value"]
            if tag == "VAC":
                raw_data["ac_voltage_v"] = float(val) / 1000.0  # mV -> V
            elif tag == "SCANRATE":
                raw_data["scan_rate_v_s"] = float(val) / 1000.0   # mV/s -> V/s
            elif tag == "SCANFWD":
                raw_data["scan_fwd_v_s"] = float(val) / 1000.0    # mV/s -> V/s
            elif tag == "SCANREV":
                raw_data["scan_rev_v_s"] = float(val) / 1000.0    # mV/s -> V/s
            else:
                raw_data[tag] = val
        elif "checked" in child.attrib:
            raw_data[tag] = child.attrib["checked"]
        elif "index" in child.attrib:
            raw_data[tag] = child.attrib["index"]
            
    return raw_data

def parse_gsequence(file_path: str) -> SequenceConfig:
    """
    Parses a Gamry .GSequence XML file into a validated SequenceConfig.
    """
    config = SequenceConfig()

    if not os.path.exists(file_path):
        print(f"Warning: XML sequence file {file_path} not found. Using defaults.")
        return config

    try:
        tree = ET.parse(file_path)
        root = tree.getroot()

        classname_to_model = {
            "OCP": (OCPConfig, "ocp"),
            "EISPOT": (EISConfig, "eis"),
            "POLRES": (LPRConfig, "lpr"),
            "CYCPOL": (CPPConfig, "cpp"),
        }

        parsed: Dict[str, Any] = {}
        for element in root.findall("element"):
            classname_el = element.find("classname")
            if classname_el is None:
                continue
            classname = classname_el.text.upper()

            if classname in classname_to_model:
                model_cls, key = classname_to_model[classname]
                raw_data = parse_element_params(element)
                parsed[key] = model_cls(**raw_data)

        config = config.model_copy(update=parsed)
    except Exception as e:
        print(f"Error parsing GSequence XML {file_path}: {e}")

    return config

def compile_gsequence(xml_path: str, json_path: str) -> SequenceConfig:
    """Parse a .GSequence and write it back out as a sequence.json."""
    config = parse_gsequence(xml_path)
    config.save(json_path)
    return config
