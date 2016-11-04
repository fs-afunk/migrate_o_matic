import http.client
import random
import string
import xml.etree.ElementTree as ET


class Client:
    """A class to interact with Plesk Installations"""

    def __init__(self, host, port=8443, protocol='https', ssl_unverified=False, verbose=False):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.secret_key = None
        self.ssl_unverified = ssl_unverified
        self.verbose = verbose
        self.login = None
        self.password = None

    def set_credentials(self, login, password):
        self.login = login
        self.password = password

    def set_secret_key(self, secret_key):
        self.secret_key = secret_key

    def __query(self, request):
        headers = {"Content-type": "text/xml", "HTTP_PRETTY_PRINT": "TRUE"}

        if self.secret_key:
            headers["KEY"] = self.secret_key
        else:
            headers["HTTP_AUTH_LOGIN"] = self.login
            headers["HTTP_AUTH_PASSWD"] = self.password

        if 'https' == self.protocol:
            if self.ssl_unverified:
                conn = http.client.HTTPSConnection(self.host, self.port,
                                                   context=ssl._create_unverified_context())
            else:
                conn = http.client.HTTPSConnection(self.host, self.port)
        else:
            conn = http.client.HTTPConnection(self.host, self.port)

        conn.request("POST", "/enterprise/control/agent.php", request, headers)
        response = conn.getresponse()
        data = response.read()
        return data.decode("utf-8")

    def get_info(self, req_type, req_info, req_filter=None):
        """
        Takes the reqType, reqInfo, and reqFilter, and builds an XML request (because who likes to make XML?)
        Passes said XML to __query to get the XML result, then makes it usable.

        :param req_type: The type of request, can be customer, webspace (subscription), or site (domain)
        :param req_info: The type of information we're looking for.  Probably gen_info or hosting
        :param req_filter: A filter to specify what object we're looking for
        :return: An XML element object rooted at the response section.  Returns False if entity not found
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        req_type_elm = ET.SubElement(packet_elm, req_type)
        get_elm = ET.SubElement(req_type_elm, 'get')
        req_filter_elm = ET.SubElement(get_elm, 'filter')
        if req_filter:
            for entity_filter in req_filter.items():
                req_filter_key_elm = ET.SubElement(req_filter_elm, entity_filter[0])
                req_filter_key_elm.text = entity_filter[1]
        dataset_elm = ET.SubElement(get_elm, 'dataset')
        ET.SubElement(dataset_elm, req_info)

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_et = ET.fromstring(response)

        if res_et.find('.//status').text == 'error':
            return False
        else:
            return res_et.find('.//id').text

    def get_protected_dirs(self, site_id):
        """
        Takes the reqType, reqInfo, and reqFilter, and builds an XML request (because who likes to make XML?)
        Passes said XML to __query to get the XML result, then makes it usable.

        :param site_id: A filter to specify what object we're looking for
        :return: An XML element object rooted at the response section.  Returns False if entity not found
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        req_type_elm = ET.SubElement(packet_elm, 'protected-dir')
        get_elm = ET.SubElement(req_type_elm, 'get')
        req_filter_elm = ET.SubElement(get_elm, 'filter')
        req_filter_key_elm = ET.SubElement(req_filter_elm, 'site-id')
        req_filter_key_elm.text = site_id

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_et = ET.fromstring(response)

        if res_et.find('.//status').text == 'error':
            return False
        else:
            protected_dirs = []
            for result_elm in res_et.findall('.//result'):
                res_name = result_elm.find('.//name').text
                if res_name != 'plesk-stat':
                    protected_dirs.append(res_name)

            return protected_dirs

    def get_customer_id(self, login_id):
        """
        Takes the reqType, reqInfo, and reqFilter, and builds an XML request (because who likes to make XML?)
        Passes said XML to __query to get the XML result, then makes it usable.

        :param login_id: The username for the control panel user
        :return: A list with the customer id and the customer pretty name.  Returns False if entity not found
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        req_type_elm = ET.SubElement(packet_elm, 'customer')
        get_elm = ET.SubElement(req_type_elm, 'get')
        req_filter_elm = ET.SubElement(get_elm, 'filter')
        req_filter_key_elm = ET.SubElement(req_filter_elm, 'login')
        req_filter_key_elm.text = login_id
        dataset_elm = ET.SubElement(get_elm, 'dataset')
        ET.SubElement(dataset_elm, 'gen_info')

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_et = ET.fromstring(response)

        if res_et.find('.//status').text == 'error':
            return False
        else:
            returnee = []
            returnee[0] = res_et.find('.//id').text
            returnee[1] = res_et.find('.//pname').text
            return returnee

    def get_site_id(self, name):
        """
        Takes the reqType, reqInfo, and reqFilter, and builds an XML request (because who likes to make XML?)
        Passes said XML to __query to get the XML result, then makes it usable.

        :param name: The name of the site
        :return: A list with the customer id and the customer pretty name.  Returns False if entity not found
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        req_type_elm = ET.SubElement(packet_elm, 'site')
        get_elm = ET.SubElement(req_type_elm, 'get')
        req_filter_elm = ET.SubElement(get_elm, 'filter')
        req_filter_key_elm = ET.SubElement(req_filter_elm, 'name')
        req_filter_key_elm.text = name
        dataset_elm = ET.SubElement(get_elm, 'dataset')
        ET.SubElement(dataset_elm, 'gen_info')

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_et = ET.fromstring(response)

        if res_et.find('.//status').text == 'error':
            return False
        else:
            return res_et.find('.//id').text

    def set_info(self, set_entity, set_type, set_info, set_filter=None):
        """
        Submits a query to the Plesk API to set some information, such as create customer
        :param set_entity: What type of entity we're modifying - webspace, customer, etc.
        :param set_type: What type of information we're giving plesk - gen_info, hosting, etc.
        :param set_info: A dict containing key/value pairs of hosting/gen_info information
        :param set_filter: A dict with two members, 'key' and 'value' describing what we're modifying
        :return: Boolean with success
        """
        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        set_entity_elm = ET.SubElement(packet_elm, set_entity)
        set_elm = ET.SubElement(set_entity_elm, 'set')
        set_filter_elm = ET.SubElement(set_elm, 'filter')
        if set_filter:
            reqFilterKeyElm = ET.SubElement(set_filter_elm, set_filter['key'])
            reqFilterKeyElm.text = set_filter['value']
        dataset_elm = ET.SubElement(set_elm, 'dataset')
        setTypeElm = ET.SubElement(dataset_elm, set_type)
        for infolet in set_info.items():
            infolet_elm = ET.SubElement(setTypeElm, infolet[0])
            infolet_elm.text = infolet[1]

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_elm = ET.fromstring(response)
        res_info_elm = res_elm.find('result')

        if res_info_elm.text == 'ok':
            return True
        else:
            return False

    def set_webspace(self, hosting_info, site_id):
        """
        Creates an entity in plesk of type add_entity, and pre-populates it with information.

        :param hosting_info: A dict containing key/value pairs of hosting information
        :param site_id: This is the ID for the site to update
        :return: list with status and Id if success, or status and error if failure
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        set_entity_elm = ET.SubElement(packet_elm, 'webspace')
        set_elm = ET.SubElement(set_entity_elm, 'set')
        filter_elm = ET.SubElement(set_elm, 'filter')
        id_elm = ET.SubElement(filter_elm, 'id')
        id_elm.text = site_id
        values_elm = ET.SubElement(set_elm, 'values')
        hosting_elm = ET.SubElement(values_elm, 'hosting')
        vrt_hst_elm = ET.SubElement(hosting_elm, 'vrt_hst')
        for hostlet in hosting_info.items():
            property_elm = ET.SubElement(vrt_hst_elm, 'property')
            hostlet_name_elm = ET.SubElement(property_elm, 'name')
            hostlet_name_elm.text = hostlet[0]
            hostlet_value_elm = ET.SubElement(property_elm, 'value')
            hostlet_value_elm.text = hostlet[1]

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_elm = ET.fromstring(response)

        if res_elm.find('.//status').text == 'ok':
            return ['ok', res_elm.find('.//id').text]
        else:
            return [res_elm.find('.//status').text, res_elm.find('.//errtext').text]

    def add_webspace(self, gen_setup, hosting_type, hosting_info, hosting_ip, hosting_plan):
        """
        Creates an entity in plesk of type add_entity, and pre-populates it with information.

        :param gen_setup: A dict containing key/value pairs of gen_info information
        :param hosting_type: If creating a webspace or forward, what kind of entity we're creating
        :param hosting_info: If creating a webspace or forward, a dict containing key/value pairs of hosting information
        :param hosting_plan: If creating a webspace, which plan to use
        :param hosting_ip: If creating a webspace, which IP address to bind to
        :return: list with status and Id if success, or status and error if failure
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        add_entity_elm = ET.SubElement(packet_elm, 'webspace')
        add_elm = ET.SubElement(add_entity_elm, 'add')
        gen_info_elm = ET.SubElement(add_elm, 'gen_setup')
        gen_setup['htype'] = hosting_type
        gen_setup['ip_address'] = hosting_ip
        for infolet in gen_setup.items():
            infolet_elm = ET.SubElement(gen_info_elm, infolet[0])
            infolet_elm.text = infolet[1]
        hosting_elm = ET.SubElement(add_elm, 'hosting')
        hosting_type_elm = ET.SubElement(hosting_elm, hosting_type)
        for hostlet in hosting_info.items():
            property_elm = ET.SubElement(hosting_type_elm, 'property')
            hostlet_name_elm = ET.SubElement(property_elm, 'name')
            hostlet_name_elm.text = hostlet[0]
            hostlet_value_elm = ET.SubElement(property_elm, 'value')
            hostlet_value_elm.text = hostlet[1]
        hosting_ip_elm = ET.SubElement(hosting_type_elm, 'ip_address')
        hosting_ip_elm.text = hosting_ip
        hosting_plan_elm = ET.SubElement(add_elm, 'plan-name')
        hosting_plan_elm.text = hosting_plan

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_elm = ET.fromstring(response)

        if res_elm.find('.//status').text == 'ok':
            return ['ok', res_elm.find('.//id').text]
        else:
            return [res_elm.find('.//status').text, res_elm.find('.//errtext').text]

    def add_customer(self, customer_name):
        """
        Creates an entity in plesk of type add_entity, and pre-populates it with information.

        :param customer_name: A pretty version of the customer's name.
        :return: id of created entity
        """

        packet_elm = ET.Element('packet', {'version': '1.6.3.5'})
        add_entity_elm = ET.SubElement(packet_elm, 'customer')
        add_elm = ET.SubElement(add_entity_elm, 'add')
        gen_info_elm = ET.SubElement(add_elm, 'gen_info')
        pname_elm = ET.SubElement(gen_info_elm, 'pname')
        pname_elm.text = customer_name
        login_elm = ET.SubElement(gen_info_elm, 'login')

        # Make a friendly customer login - strip out non-alphanum, limit to 20 characters, add _cp
        login_id = re.sub('[\W_]+', '', customer_name).lower()[:20] + '_cp'
        login_elm.text = login_id

        passwd_elm = ET.SubElement(gen_info_elm, 'passwd')
        passwd_elm.text = ''.join(random.SystemRandom().choice(string.ascii_uppercase + string.ascii_lowercase +
                                                               string.digits + '!@#$%^&*()/[]{}') for _ in range(34))

        email_elm = ET.SubElement(gen_info_elm, 'email')
        email_elm.text = 'hostmaster@firstscribe.com'

        if self.verbose:
            print(ET.tostring(packet_elm, 'utf-8'))

        response = self.__query(ET.tostring(packet_elm, 'utf-8'))

        if self.verbose:
            print(response)

        res_elm = ET.fromstring(response)

        if res_elm.find('.//status').text == 'ok':
            return res_elm.find('.//id').text
        else:
            return False
