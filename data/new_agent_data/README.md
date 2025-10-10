# new\_agent\_data


## results\_agents\_new.zip

An updated iteration of the results\_agents.zip data. Obtained by running a slighly modified version (attached) of the dataset\_maker\_agents\_raw\_data in https://github.com/ariannamorettj/BnF_Analysis.
In the modified version, batch size was set to 2000 (this made the querying faster), and the

## dataset\_maker\_agents\_raw\_data\_updated.py

Batch size of queries was changed to 2000 (increased speed) and the foaf:name property of agent queries was set to be optional. Additionally, foaf:familyName, foaf:givenName and rdf:type were added as optional properties of the queries. 