import http.client
import ssl
import xml.dom.minidom


class PleskApiClient:
    """A class to interact with Plesk Installations"""

    def __init__(self, host, port=8443, protocol='https', ssl_unverified=False):
        self.host = host
        self.port = port
        self.protocol = protocol
        self.secret_key = None
        self.ssl_unverified = ssl_unverified

    def set_credentials(self, login, password):
        self.login = login
        self.password = password

    def set_secret_key(self, secret_key):
        self.secret_key = secret_key

    def __query(self, request):
        headers = {}
        headers["Content-type"] = "text/xml"
        headers["HTTP_PRETTY_PRINT"] = "TRUE"

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

    def getInfo(self, reqType, reqInfo, reqFilter=None):
        """
        Takes the reqType, reqInfo, and reqFilter, and builds an XML request (because who likes to make XML?)
        Passes said XML to __query to get the XML result, then makes it usable.  Basically, a big DOM wrapper.

        :param reqType: The type of request, can be customer, webspace (subscription), or site (domain)
        :param reqInfo: The type of information we're looking for.  Probably gen_info or hosting
        :param reqFilter: A filter to specify what object we're looking for
        :return: A dict that contains key:value pairs of the data
        """
        impl = xml.dom.minidom.getDOMImplementation()

        reqDom = impl.createDocument(None, "request", None)

        packetElm = reqDom.createElement('packet')
        packetElm.setAttribute('version', '1.6.3.5')
        customerElm = reqDom.createElement(reqType)
        getElm = reqDom.createElement('get')
        reqFilterElm = reqDom.createElement('reqFilter')
        if reqFilter is not None:
            reqFilterKeyElm = reqDom.createElement(reqFilter['key'])
            reqFilterKeyElm.appendChild(reqDom.createTextNode(reqFilter['value']))
            reqFilterElm.appendChild(reqFilterKeyElm)
        getElm.appendChild(reqFilterElm)
        datasetElm = reqDom.createElement('dataset')
        datasetElm.appendChild(reqDom.createElement(reqInfo))
        getElm.appendChild(datasetElm)
        customerElm.appendChild(getElm)
        packetElm.appendChild(customerElm)
        reqDom.appendChild(packetElm)
        reqDom.formatOutput = True

        response = self.__query(reqDom.saveXML())

        resDom = xml.dom.minidom.parseString(response)
        reqInfoDom = resDom.getElementsByTagName(reqInfo)[0]

        responseDict = {}
        for element in reqInfoDom:
            responseDict[element.nodeName] = element.nodeValue

        return responseDict

web2 = PleskApiClient('web2.firstscribe.com')
web2.set_credentials('admin','m9AqxP<O&*CEXWzvR-MajUFMqvcb.(B,M*j@7}>v9rlO_62Rh')
response = web2.getInfo('customer','gen_info',{'key':'id', 'value':'2'})
response
