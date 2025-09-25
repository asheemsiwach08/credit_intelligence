from typing import List, Optional
from pydantic import BaseModel, Field
import uuid

########################### Classification Agent Schemas ##############################
class TableColumns(BaseModel):
    column_name: str = Field(None, description="The name of the column")
    column_type: str = Field(None, description="The type of the column")

class URLAnalysis(BaseModel):
    domains: List[str] = Field(default_factory=list, description="List of domains extracted from the provided URLs")
    paths: List[str] = Field(default_factory=list, description="Key path segments from the URLs")
    query_params_present: List[str] = Field(default_factory=list, description="List of query parameter keys found in the URLs")
    inferred_context: Optional[str] = Field(None, description="Short inference from the URL structure, brand, section, locale, etc.")

class TableDetails(BaseModel):
    best_table: Optional[str] = Field(None, description="The most similar table name if found, otherwise provide the best match table name")
    similarity_note: Optional[str] = Field(None, description="Reason why the table matches or why none match")
    is_completely_different: bool = Field(False, description="True if query does not match any table, else False")
    output_format: List[TableColumns] = Field(None, description="The output format of the llm model to use and the schema to use, Example: [{'name': 'Rakesh', 'phone': '9876543210'}]")
    
class Entity(BaseModel):
    entity: str = Field(..., description="Extracted entity text")
    type: str = Field(..., description="Entity type, e.g., person, organization, product, location, date, other")

class Prompt(BaseModel):
    system_message: str = Field(None, description="The system message to use for the prompt")
    user_prompt: str = Field(None, description="This prompt will be used to extract the data, should be detailed and comprehensive")
    search_prompt: str = Field(None, description="This prompt will be used to search the data from the web, it will be should and concise")

class ClassificationAgentRequest(BaseModel):
    usecase: str = Field(...,description="The schema usecase chosen to classify the data")
    is_classified: bool = Field(False, description="Whether the data is classified successfully with a schema usecase")
    url_analysis: URLAnalysis = Field(default_factory=URLAnalysis, description="Structured analysis of the provided URLs")
    table_details: TableDetails = Field(default_factory=TableDetails, description="Similarity comparison or providing the best match table name and details")
    entity: str = Field(None, description="one wordname of item found (except the domain name) in the url or details provided to you by the user")
    reasoning: Optional[str] = Field(None, description="Brief explanation of why the usecase was chosen")
    prompt: Prompt = Field(default_factory=Prompt, description="The prompt to use for the prompt")


# class ClassificationAgentRequest(BaseModel):
#     keyword: str = Field("Not Found", description="The schema to classify the data")
#     entity: str = Field(None, description="The name of item found (except the domain name) in the url or details provided to you by the user")
#     is_classified: bool = Field(False, description="Whether the data is classified")

############################### Sniffer Generate Config Agent Schemas ####################################

class GenerateConfigAgentRequest(BaseModel):
    usecase: str = Field(None, description="The one word schema to classify the data")
    entity: str = Field(None, description="one wordname of item found (except the domain name) in the url or details provided to you by the user")
    keywords: List[str] = Field(None, description="The keywords matching the urls or details provided to you by the user")
    table_name: str = Field(None, description="one word table name to store the data in the database")
    primary_key: str = Field(None, description="The primary key to identify the data in the table")
    output_format: List[TableColumns] = Field(None, description="The output format of the llm model to use and the schema to use, Example: [{'name': 'Rakesh', 'phone': '9876543210'}]")
    scraper_system_message: str = Field(None, description="The system message to use for the scraper")
    scraper_prompt: str = Field(None, description="The prompt to use for the scraper")
    refinement_prompt: str = Field(None, description="The prompt to use for the refinement")

############################### Sniffer AI Schemas ####################################
class SnifferAIRequest(BaseModel):
    # entity: Optional[str] = Field(None, description="The entity to scrape")
    urls: Optional[List[str]] = Field(None, description="The url to scrape")
    prompt: Optional[str] = Field(None, description="The prompt to scrape the data")
    # source: Optional[str] = Field(None, description="Type of data to extract") # "lenders", "banking"
    googleSearch: Optional[bool] = Field(False, description="Whether to enable google search")
    snifferTool: Optional[bool] = Field(False, description="Whether to enable sniffer tool")
    enableSearch: Optional[bool] = Field(False, description="Whether to enable search")
    enableRefinement: Optional[bool] = Field(False, description="Whether to enable refinement")
    keywordsToSearch: Optional[List[str]] = Field(None, description="The keywords to search")

class SnifferAIResponse(BaseModel):
    success: bool = Field(..., description="Whether the request was successful")
    message: str = Field(..., description="The message from the response")

class SnifferLendersRoiRequest(BaseModel):
    table_name: str = Field(..., description="The table name to store the data")
    interval: int = Field(1, description="The days interval to scrape the data")
    # id: Optional[str] = Field(str(uuid.uuid4()), description="The id of the lender")
    # googleSearch: Optional[bool] = Field(False, description="Whether to enable google search")
    # entity: str = Field(..., description="The entity to scrape")

############################### Analyze Query Schemas ####################################
class AnalyzeQueryResponse(BaseModel):
    responseContent: str = Field(..., description="The response content")
    urlIncluded: bool = Field(..., description="Whether the url is included in the response")


############################### Lenders Extract Schemas ##################################
class LendersExtractSchema(BaseModel):
    lender: str
    alias: str
    officialwebsite: str
    homeloanwebsite: str
    lendertype: str
    foirsalaried: str
    foirselfsalaried: str
    foir: str
    homeloanroi: str
    laproi: str
    homeloanltv: str
    lapltv: str
    listofdocuments: str
    minimumcoborrowerincome: str
    minimumcreditscore: str
    remarks: str
    acceptedagreementtype: str
    acceptedusagetype: str
    mitc: str
    loanproducts: str
    targetcustomers: str
    eligibilitycriteria: str
    eligibleprofessiontype: str
    keyfeatures: str
    specialoffersavailable: str
    customersupportcontactnumbers: str
    loanapprovaltime: str
    processingtime: str
    minimumloanamount: str
    maximumloanamount: str
    loantenurerange: str
    primaryborrowerincomerange: str
    coborrowerincomerange: str
    processingfees: str
    prepaymentcharges: str
    foreclosurecharges: str
    approvedpropertytypes: str
    propertytypespecifications: str
    sourceurls: List[str]

class LendersExtractSchemaOutput(BaseModel):
    output: LendersExtractSchema

############################### Sniffer Extract Schemas ##################################

class SnifferOutputData(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None
    specialization: Optional[str] = None
    experience: Optional[str] = None

# Direct list type - no wrapper needed
class SnifferExtractSchema(BaseModel):
    output: List[SnifferOutputData]

############################# IOCL Extract Schemas ##################################
class IOCLOutputData(BaseModel):
    name: str
    phone: str
    email: Optional[str] = None
    city: Optional[str] = None
    address: Optional[str] = None

class IOCLExtractSchema(BaseModel):
    output: List[IOCLOutputData]

########################## Lenders Gemini Search Response ###################################
class InterestRange(BaseModel):
    min_interest_rate: float
    max_interest_rate: float

class LoanTenureRange(BaseModel):
    min_loan_tenure_in_years: int
    max_loan_tenure_in_years: int

class LoanAmountRange(BaseModel):
    min_loan_amount: int
    max_loan_amount: int    

class LendersGeminiSearchResponse(BaseModel):
    lender_name: str
    home_loan_interest_rate_range: InterestRange
    loan_against_property_interest_rate_range: InterestRange
    home_loan_to_value: str
    loan_against_property_loan_to_value: str
    minimum_credit_score: int
    loan_amount_range: LoanAmountRange
    loan_tenure_range: LoanTenureRange
    loan_approval_time: str
    processing_fees: str
    processing_time: str
    special_offers_available: str




    