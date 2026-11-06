import utils


def test_pdf_name_for_work_order():
    name = utils.pdf_name(
        {
            "Order_ID": "W-108624",
            "Order_Type": "RO",
            "SO": "5425.0",
            "Customer_name": "POFI Construction",
            "Ship_to": "2740 Cropsey",
        }
    )
    assert name == "W-108624_RO.5425_POFI Construction_2740 Cropsey"


def test_pdf_name_for_shipment_order():
    name = utils.pdf_name(
        {
            "Order_ID": "3501",
            "Order_Type": "SO",
            "SO": 3501.0,
            "Customer_name": "ExampleCo",
            "Ship_to": "Bronx",
        }
    )
    assert name == "Shipment 3501_SO.3501_ExampleCo_Bronx"
