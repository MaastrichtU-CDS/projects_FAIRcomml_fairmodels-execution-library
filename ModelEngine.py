import rdflib
import os
from string import Template
import math

class FML:
    prefix = "https://fairmodels.org/ontology.owl#"
    logisticRegression = prefix + "Logistic_Regression"
    linearPredictor = prefix + "linear_predictor"
    dockerExecution = prefix + "docker_execution"

class ModelExecutor:
    def __init__(self, modelUri, modelEngine):
        self.modelEngine = modelEngine
        self.modelUri = modelUri
        self.modelParameters = None
        self.parameterValueForTermLists = None

    def executeModelOnDataFrame(self, cohortDataFrame):
        return cohortDataFrame

    def executeModel(self, inputValues):
        return None

    def getModelParameters(self):
        if self.modelParameters is None:
            queryResults = self.modelEngine.performQueryFromFile("linearParams", mappings={"modelUri": self.modelUri})
            output = dict()
            for row in queryResults:
                output[str(row["inputFeature"])] = {
                    "featureName": str(row["inputFeatureName"]),
                    "beta": float(str(row["beta"]))
                }
            self.modelParameters = output
        return self.modelParameters
    def replaceParameterToLocalValue(self, parameterId, inputValue):
        paramMapping = self.getValueForTermList(parameterId)
        if paramMapping is not None:
            if inputValue in paramMapping:
                inputValue = paramMapping[inputValue]
        return inputValue
    def getValueForTermList(self, modelParameter):
        ## does a lookup on the translation values for a given model parameter
        if self.parameterValueForTermLists is None:
            self.parameterValueForTermLists = {}
            queryResults = self.modelEngine.performQueryFromFile("valueForTermList", mappings={"modelParameter": modelParameter})
            for row in queryResults:
                inputFeatureName = str(row["inputFeature"])
                termName = str(row["term"])
                termValue = row["value"]

                # Replace termValue types
                termValueNew = str(termValue)
                termValueType = str(termValue.datatype)
                if termValueType=="http://www.w3.org/2001/XMLSchema#int":
                    termValueNew = int(str(termValue))
                if termValueType=="http://www.w3.org/2001/XMLSchema#integer":
                    termValueNew = int(str(termValue))
                if termValueType=="http://www.w3.org/2001/XMLSchema#double":
                    termValueNew = float(str(termValue))
                termValue = termValueNew

                # insert termValues in list
                if inputFeatureName not in self.parameterValueForTermLists:
                    self.parameterValueForTermLists[inputFeatureName] = {}
                self.parameterValueForTermLists[inputFeatureName][termName] = termValue
        
        if modelParameter in self.parameterValueForTermLists:
            return self.parameterValueForTermLists[modelParameter]
        else:
            return None

class DockerExecutor(ModelExecutor):
    def executeModel(self, inputValues):
        return super().executeModel(inputValues)

class LogisticRegression(ModelExecutor):        
    def executeModelOnDataFrame(self, cohortDataFrame):
        modelParameters = self.getModelParameters()

        reverseIndex = {}
        keyValue = {}
        for key in modelParameters:
            parameter = modelParameters[key]

            if parameter["featureName"] not in cohortDataFrame.columns:
                raise NameError("Could not find column %s" % parameter["featureName"])
            reverseIndex[parameter["featureName"]] = key
            keyValue[key] = parameter["featureName"]

        myDf = cohortDataFrame.rename(columns=reverseIndex)
        myDf["probability"] = None

        for index, row in myDf.iterrows():
            # convert short column name to long version
            try:
                myDf.at[index, "probability"] = self.executeModel(row)
            except Exception as ex:
                print(ex)
        cohortDataFrame = myDf.rename(columns=keyValue)
        return cohortDataFrame
    def executeModel(self, inputValues):
        modelParameters = self.getModelParameters()
        if inputValues is not None:
            intercept = self.__getInterceptParameter()
            weightedSum = self.__calculateWeightedSum(modelParameters, inputValues)
            lp = intercept + weightedSum
            probability = 1 / (1 + math.exp(-1 * lp))
            return probability
    def __calculateWeightedSum(self, modelParameters, inputValues):
        lp = float(0)
        for parameterId in modelParameters:
            inputValue = self.replaceParameterToLocalValue(parameterId, inputValues[parameterId])
            parameter = modelParameters[parameterId]
            weightedVar = parameter["beta"] * inputValue
            lp = lp + weightedVar
        return lp
    def __getInterceptParameter(self):
        queryResults = self.modelEngine.performQueryFromFile("intercept", mappings={"modelUri": self.modelUri})
        for row in queryResults:
            return float(str(row["intercept"]))

class ModelEngine:
    def __init__(self, modelUri):
        self.__graph = rdflib.Graph()
        self.__graph.parse(modelUri, format=rdflib.util.guess_format(modelUri))
    def __getSparqlQueryFromFile(self, queryName, mappings=None):
        query = ""
        with open(os.path.join("queries", queryName + ".sparql")) as f:
            query = f.read()
        if mappings is not None:
            temp_obj = Template(query)
            query = temp_obj.substitute(**mappings)
        return query

    def performQueryFromFile(self, queryName, mappings=None):
        query = self.__getSparqlQueryFromFile(queryName=queryName, mappings=mappings)
        return self.__graph.query(query)
    
    def getModelExecutor(self):
        queryResults = self.performQueryFromFile("modelType")
        
        for resultRow in queryResults:
            algorithmTypeString = str(resultRow["algorithmType"])
            algorithmExecutionTypeString = str(resultRow["algorithmExecutionType"])

            if FML.logisticRegression == algorithmTypeString:
                if FML.linearPredictor == algorithmExecutionTypeString:
                    return LogisticRegression(str(resultRow["algorithm"]), self)
            
            if FML.dockerExecution == algorithmExecutionTypeString:
                print("Unknown algorithm type, but it is definately a docker-based execution")
                return DockerExecutor(str(resultRow["algorithm"]), self)
        
        return None