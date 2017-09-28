import pytest

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException


@pytest.fixture(scope="module")
def driver(request):
    driver = webdriver.Chrome()
    driver.implicitly_wait(3)

    def cleanup():
        driver.close()

    request.addfinalizer(cleanup)
    return driver


def test_01_add_a_server(driver):
    # Users opens the homepage
    driver.get('localhost:5000/')
    # Homepage provides a button to add server
    add_btn = driver.find_element_by_partial_link_text('Add Server')
    # User clicks on the button and sees the new server form
    add_btn.click()
    heading = driver.find_element_by_tag_name('h2')
    assert heading.text == 'New Server'
    # User enters the details of the server and submits the form
    hostname = driver.find_element_by_id('hostname')
    hostname.send_keys('dummy.example.com')
    ip = driver.find_element_by_id('ip')
    ip.send_keys('0.0.0.0')
    ldap_pass = driver.find_element_by_id('ldap_password')
    ldap_pass.send_keys('password')
    gluu = driver.find_element_by_id('gluu_server')
    gluu.click()
    gluu.submit()
    # User is redirected back to the hompage where his server is listed
    assert 'dummy.example.com' in driver.find_element_by_tag_name('body').text


def test_02_change_server_details(driver):
    hostname = 'dummy.example.com'
    # User sees his server listed in the homepage in a table
    assert hostname in driver.find_element_by_tag_name('table').text
    # User clicks the "Edit" button in his/her server row
    rows = driver.find_elements_by_tag_name('tr')
    for row in rows:
        if hostname in row.text:
            row.find_element_by_link_text('Edit').click()
            break
    # User is taken to the "Update Server Details" page
    heading = driver.find_element_by_tag_name('h2')
    assert heading.text == "Update Server Details"
    # User updates some data (ip address) of the server
    ip = driver.find_element_by_id('ip')
    ip.clear()
    ip.send_keys('1.1.1.1')
    ip.submit()
    # User is redirected back to the hompage where his server is listed
    assert '1.1.1.1' in driver.find_element_by_tag_name('body').text


def test_03_remove_server(driver):
    hostname = 'dummy.example.com'
    # User sees his server listed in the homepage in a table
    assert hostname in driver.find_element_by_tag_name('table').text
    # User clicks the "Remove" button in his/her server row
    rows = driver.find_elements_by_tag_name('tr')
    for row in rows:
        if hostname in row.text:
            row.find_element_by_link_text('Remove').click()
            break
    # User sees a confirmation dialog and confirms the delete
    driver.find_element_by_link_text('Confirm').click()
    # User sees a message that server is removed
    assert hostname in driver.find_element_by_class_name('alert-success').text
    # User no longer sees the server listed in the dashboard
    try:
        table = driver.find_element_by_tag_name('table')
        assert hostname not in table.text
    except NoSuchElementException:
        # This means there is no table at all becuase there are no servers
        assert True
