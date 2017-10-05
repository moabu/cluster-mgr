import pytest

from selenium import webdriver
from selenium.webdriver.support.ui import Select


@pytest.fixture(scope="module")
def driver(request):
    driver = webdriver.Chrome()

    def cleanup():
        driver.close()

    request.addfinalizer(cleanup)
    return driver


def set_version_below_support(driver):
    """Sets the gluu_version variable in App Configuration below the Cache
    support version of 3.1.1
    """
    driver.get('localhost:5000/configuration/')
    gluu_version = Select(driver.find_element_by_name('gluu_version'))
    gluu_version.select_by_visible_text('3.0.1')
    driver.find_element_by_id('update').click()


def set_supported_version(driver):
    driver.get('localhost:5000/configuration/')
    gluu_version = Select(driver.find_element_by_name('gluu_version'))
    gluu_version.select_by_visible_text('3.1.1')
    driver.find_element_by_id('update').click()


def test_01_cache_manager_error_for_unsupported_versions(driver):
    # User opens the cache management url
    url = 'localhost:5000/cache/'
    driver.get(url)
    heading = driver.find_element_by_tag_name('h2')
    # User sees the title saying Cache Management
    assert heading.text == 'Cache Management'

    # When the gluu server version is set to lower than the supported version
    # the users sees a error message
    set_version_below_support(driver)
    driver.get(url)
    error_box = driver.find_element_by_class_name('jumbotron')
    assert 'Module not available' in error_box.text


def test_02_cache_manager_show_servers_for_supported_versions(driver):
    # When the gluu_server version is set to a supported version the user
    # sees a list of servers and their cache methods
    url = 'localhost:5000/cache/'
    set_supported_version(driver)
    driver.get(url)
    table = driver.find_element_by_tag_name('table')
    assert 'Hostname' in table.text
    assert 'Cache Method' in table.text


def test_03_change_cache_method_to_cluster(driver):
    url = 'localhost:5000/cache/'
    driver.get(url)

    # The user clicks the "Change button
    driver.find_element_by_id('changeBtn').click()

    # User see the cache clustering form
    assert 'Cache Clustering' in driver.find_element_by_tag_name('h2').text

    # the form gives the option to configure the cache servers in either
    # cluster or in sharding mode
    form = driver.find_element_by_tag_name('form')
    assert 'SHARDING' in form.text
    assert 'CLUSTER' in form.text

    # user chooses the cluster option and submits the form
    cluster_radio = driver.find_element_by_id("CLUSTER")
    cluster_radio.click()
    submit = driver.find_element_by_id("submit")
    submit.click()

    # TODO verify the different steps in the cache cluster setup process
