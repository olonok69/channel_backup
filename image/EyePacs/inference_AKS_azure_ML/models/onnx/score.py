import json
import numpy as np
import onnxruntime
import sys
import os
from azureml.core.model import Model
import time
from transformers import ViTImageProcessor
import base64
import io
from PIL import Image


def init():
    global qsession, input_nameq, output_nameq, dsession, input_named, output_named, feature_extractor, label_dic_quality, label_dic_detection
    path_model_detection ="retina_detection.onnx"
    path_model_quality ="retina_quality.onnx"
    # Load the model QUALITY   
    qsession = onnxruntime.InferenceSession(path_model_quality, providers=["CPUExecutionProvider"])
    input_nameq = qsession.get_inputs()[0].name
    output_nameq = qsession.get_outputs()[0].name 
    # Load the model Detection   
    dsession = onnxruntime.InferenceSession(path_model_detection, providers=["CPUExecutionProvider"])
    input_named = dsession.get_inputs()[0].name
    output_named = dsession.get_outputs()[0].name 
    model_name_or_path = 'google/vit-base-patch16-224-in21k'
    feature_extractor = ViTImageProcessor.from_pretrained(model_name_or_path, do_normalize =False, do_rescale=True )
    label_dic_quality ={"good":0, "usable": 1,"reject":2}
    label_dic_detection ={"NO_DR":0, "DR":1}
    
def run(input_data):
    '''Purpose: evaluate test input in Azure Cloud using onnxruntime.
        We will call the run function later from our Jupyter Notebook 
        so our azure service can evaluate our model input in the cloud. '''

    try:
        # load in our data, convert to readable format
        requests_json = json.loads(input_data.encode("utf-8"))
        
        image_bytes = base64.b64decode(requests_json.get("data"))
        image= Image.open(io.BytesIO(image_bytes))
        inputs_t = np.array( feature_extractor(image, return_tensors='pt')['pixel_values'])
        
        
        # pass input data to do model inference with ONNX Runtime Quality Model
        start = time.time()
        outputsq = qsession.run([output_nameq], {input_nameq: inputs_t})[0]       
        logits, probabilities, predicted_class = get_probs(outputsq)
        output_quality = label_map(predicted_class=predicted_class, label_dic=label_dic_quality, probabilities=probabilities)
        # If probability reject < .33
        output_detection = {}
        if output_quality['reject']< 0.33:
            outputsd = dsession.run([output_named], {input_named: inputs_t})[0]       
            logits, probabilities, predicted_class = get_probs(outputsd)
            output_detection = label_map(predicted_class=predicted_class, label_dic=label_dic_detection, probabilities=probabilities)
            
        
        end = time.time()
        if output_detection.keys() == 0:
            output_detection = {"output": "not posible Output due to low quality Image"}
        result_dict = {"result_quality": output_quality,
                       "result_detection": output_detection,
                      "time_in_sec": [end - start]}
    except Exception as e:
        result_dict = {"error": str(e)}
    
    return json.dumps(result_dict)



def label_map(predicted_class, label_dic, probabilities, threshold=.5):
    """Take the most probable labels (output of postprocess) and returns the 
    probs of each label."""
    print(f"Predicted classes: {predicted_class[0]}, label: { get_key(label_dic, predicted_class[0])}")
    print("\n")
    output_probs = {}
    print("All Probabilities:")
    for prob, key in zip(probabilities[0], range(0, len(probabilities[0]))):
        label = get_key(label_dic, key)
        output_probs[label] = float(prob)
    
    return output_probs

def get_key(dict, value):
    """
    return key given a value. From a dictionary
    """
    for key, val in dict.items():
        if val == value:
            return key
    return "Value not found"


def get_probs(outputs):
    """This function takes the scores generated by the network and 
    returns the class IDs in decreasing order of probability."""

    # Get Logits
    logits = np.array(outputs)
    # Get Probabilities
    probabilities = np.exp(logits) / np.sum(np.exp(logits), axis=1, keepdims=True)
    # Get Pedicted Class
    predicted_class = np.argmax(probabilities, axis=1)
    
    return logits, probabilities, predicted_class

