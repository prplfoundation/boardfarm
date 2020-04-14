import os

import xmltodict
from boardfarm.lib.bft_logging import LoggerMeta
from zeep import Client
from zeep.wsse.username import UsernameToken

if "BFT_DEBUG" in os.environ:
    import logging.config

    logging.config.dictConfig({
        'version': 1,
        'formatters': {
            'verbose': {
                'format': '%(name)s: %(message)s'
            }
        },
        'handlers': {
            'console': {
                'level': 'DEBUG',
                'class': 'logging.StreamHandler',
                'formatter': 'verbose',
            },
        },
        'loggers': {
            'zeep.transports': {
                'level': 'DEBUG',
                'propagate': True,
                'handlers': ['console'],
            },
        }
    })


class FriendlyACS():
    __metaclass__ = LoggerMeta
    log = ""
    log_calls = ""

    model = "friendly_acs_soap"

    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs
        self.username = self.kwargs['username']
        self.password = self.kwargs['password']
        self.ipaddr = self.kwargs['ipaddr']
        self.wsdl = "http://" + self.kwargs[
            'ipaddr'] + "/ftacsws/acsws.asmx?WSDL"
        self.client = Client(wsdl=self.wsdl,
                             wsse=UsernameToken(self.username, self.password))
        self.port = self.kwargs.get('port', '80')
        self.log = ""

    name = "acs_server"

    def __str__(self):
        return "FriendlyACS"

    def close(self):
        pass

    def get(self, cpeid, param, source=0):
        # source = 0 (CPE), source = 1 (DB)
        ret = self.client.service.FTGetDeviceParameters(devicesn=cpeid,
                                                        source=source,
                                                        arraynames=[param])
        if None == ret['Params']:
            return None
        else:
            return ret['Params']['ParamWSDL'][0]['Value']

    def set(self, cpeid, attr, value):
        array_of_param = self.client.get_type(
            '{http://www.friendly-tech.com}ArrayOfParam')

        arr = array_of_param([{'Name': attr, 'Value': value}])

        # TODO: investigate push, endsession, reprovision, priority to make sure they are what we want
        self.client.service.FTSetDeviceParameters(devicesn=cpeid, \
                                                  arrayparams=arr, \
                                                  push=True, \
                                                  endsession=False, \
                                                  priority=0)

    def rpc(self, cpeid, name, content):
        ''' Invoke custom RPC on specific CM'''
        ret = self.client.service.FTRPCInvoke(devicesn=cpeid,
                                              rpcname=name,
                                              soapcontent=content)
        return xmltodict.parse(ret['Response'])

    def rpc_GetParameterAttributes(self, cpeid, name):
        content = '<cwmp:GetParameterAttributes xmlns:cwmp="urn:dslforum-org:cwmp-1-0"> <ParameterNames arrayType-="xsd:string[1]"> <string>%s</string> </ParameterNames> </cwmp:GetParameterAttributes>' % name

        ret = self.rpc(cpeid, name, content)

        return ret['cwmp:GetParameterAttributesResponse']['ParameterList'][
            'ParameterAttributeStruct']

    def rpc_GetParameterValues(self, cpeid, name):
        content = '<cwmp:GetParameterValues xmlns:cwmp="urn:dslforum-org:cwmp-1-0"> <ParameterNames arrayType="xsd:string[1]"> <string>%s</string> </ParameterNames> </cwmp:GetParameterValues>' % name

        ret = self.rpc(cpeid, name, content)

        return ret['cwmp:GetParameterValuesResponse']['ParameterList'][
            'ParameterValueStruct']['Value']['#text']

    def getcurrent(self, cpeid, param, source=0):
        self.client.service.FTGetDeviceParameters(devicesn=cpeid,
                                                  source=source,
                                                  arraynames=[param + '.'])

    def rpc_SetParameterAttributes(self, cpeid, name, set_value):
        content = '<cwmp:SetParameterAttributes xmlns:cwmp="urn:dslforum-org:cwmp-1-0"> <ParameterList arrayType="cwmp:SetParameterAttributesStruct[1]"> <SetParameterAttributesStruct> <Name>%s</Name> <NotificationChange>1</NotificationChange> <Notification>%s</Notification> <AccessListChange>0</AccessListChange> <AccessList></AccessList> </SetParameterAttributesStruct> </ParameterList> </cwmp:SetParameterAttributes>' % (
            name, set_value)

        self.rpc(cpeid, name, content)

    def rpc_AddObject(self, cpeid, obj_name):
        content = '<cwmp:AddObject xmlns:cwmp="urn:dslforum-org:cwmp-1-0"> <ObjectName>%s.</ObjectName>  <ParameterKey></ParameterKey> </cwmp:AddObject>' % obj_name
        self.rpc(cpeid, obj_name, content)

    def rpc_DeleteObject(self, cpeid, obj_name):
        content = '<cwmp:DeleteObject xmlns:cwmp="urn:dslforum-org:cwmp-1-0"> <ObjectName>%s.</ObjectName>  <ParameterKey></ParameterKey> </cwmp:DeleteObject>' % obj_name
        self.rpc(cpeid, obj_name, content)

    def is_online(self, cpeid):
        ret = self.client.service.FTCPEStatus(devicesn=cpeid)
        return ret['Online']

    def delete_cpe(self, cpeid):
        print("WARN: not impl for this class")
        pass


if __name__ == '__main__':
    import sys

    if ':' in sys.argv[1]:
        ip = sys.argv[1].split(':')[0]
        port = sys.argv[1].split(':')[1]
    else:
        ip = sys.argv[1]
        port = 80

    acs = FriendlyACS(ipaddr=ip,
                      port=port,
                      username=sys.argv[2],
                      password=sys.argv[3])

    ret = acs.rpc_GetParameterAttributes('DEAP815610DA',
                                         'Device.WiFi.SSID.1.SSID')
    print(ret['Notification'])

    ret = acs.get('DEAP815610DA', 'Device.DeviceInfo.SoftwareVersion')
    print(ret)

    ret = acs.get('DEAP815610DA', 'Device.WiFi.SSID.1.SSID')
    print(ret)
