import pytest

from selenium import webdriver


@pytest.fixture(scope="module")
def driver(request):
    driver = webdriver.Chrome()

    def cleanup():
        driver.close()

    request.addfinalizer(cleanup)
    return driver


def test_cache_manager_index(driver):
    url = 'localhost:5000/cache/'
    driver.get(url)
    heading = driver.find_element_by_tag_name('h2')
    assert heading.text == 'Cache Management'
