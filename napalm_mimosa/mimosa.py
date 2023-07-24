from napalm.base.base import NetworkDriver
from pysnmp.hlapi import *


class MimosaDriver(NetworkDriver):
    def __init__(
        self,
        hostname,
        username,
        password,
        timeout=60,
        snmp_community="public",
        optional_args=None,
    ):
        self.hostname = hostname
        self.username = username
        self.password = password
        self.timeout = timeout
        self.snmp_community = snmp_community

    def open(self):
        pass  # we don't need to open a connection for SNMP

    def close(self):
        pass  # likewise, no connection to close

    def _snmp_get(self, mib, oid=None):
        if mib.startswith("."):
            # OID provided, not MIB
            object_id = ObjectType(ObjectIdentity(mib))
        else:
            # MIB and OID provided
            object_id = ObjectType(ObjectIdentity(mib, oid, 0))

        errorIndication, errorStatus, errorIndex, varBinds = next(
            getCmd(
                SnmpEngine(),
                CommunityData(self.snmp_community),
                UdpTransportTarget((self.hostname, 161)),
                ContextData(),
                object_id,
            )
        )

        if errorIndication or errorStatus:
            return None

        result = varBinds[0][1].prettyPrint()  # return the value

        # Check if the result is a hexadecimal string
        if result.startswith("0x"):
            # Convert from hex to string
            result = bytes.fromhex(result[2:]).decode("utf-8").rstrip("\n")

        return result

    def get_facts(self):
        facts = {
            "uptime": self._snmp_get("SNMPv2-MIB", "sysUpTime"),
            "vendor": "Mimosa",
            "os_version": self._snmp_get(".1.3.6.1.4.1.43356.2.1.2.1.3.0"),
            "serial_number": self._snmp_get(".1.3.6.1.4.1.43356.2.1.2.1.2.0"),
            "model": self._snmp_get("SNMPv2-MIB", "sysDescr"),
            "hostname": self._snmp_get("SNMPv2-MIB", "sysName"),
            "fqdn": self._snmp_get("SNMPv2-MIB", "sysName"),
            "interface_list": self.get_interfaces_list(),  # SNMP does not typically provide this info
        }
        return facts

    def get_interfaces_list(self):
        interfaces = []
        for errorIndication, errorStatus, errorIndex, varBinds in nextCmd(
            SnmpEngine(),
            CommunityData(self.snmp_community),
            UdpTransportTarget((self.hostname, 161)),
            ContextData(),
            ObjectType(ObjectIdentity("IF-MIB", "ifDescr")),
            lexicographicMode=False,
        ):
            if errorIndication or errorStatus:
                return []
            else:
                for varBind in varBinds:
                    interfaces.append(str(varBind[-1]))
        return interfaces

    def get_interfaces(self):
        interfaces = {}

        # OIDs for the different interface data we want to collect
        oids = {
            "ifDescr": "1.3.6.1.2.1.2.2.1.2",
            "ifOperStatus": "1.3.6.1.2.1.2.2.1.8",
            "ifAdminStatus": "1.3.6.1.2.1.2.2.1.7",
            "ifSpeed": "1.3.6.1.2.1.2.2.1.5",
            "ifMtu": "1.3.6.1.2.1.2.2.1.4",
            "ifPhysAddress": "1.3.6.1.2.1.2.2.1.6",
        }

        # Get interface data
        for oid_name, oid in oids.items():
            for errorIndication, errorStatus, errorIndex, varBinds in nextCmd(
                SnmpEngine(),
                CommunityData(self.snmp_community),
                UdpTransportTarget((self.hostname, 161)),
                ContextData(),
                ObjectType(ObjectIdentity(oid)),
                lexicographicMode=False,
            ):
                if errorIndication or errorStatus:
                    return {}

                for varBind in varBinds:
                    try:
                        interface_index = str(varBind[0].getOid()[-1])
                    except Exception as e:
                        print(
                            f"Error while extracting index from OID: {varBind[0].prettyPrint()}. Error message: {str(e)}"
                        )
                        continue

                    interface_value = str(varBind[1])
                    if interface_index not in interfaces:
                        interfaces[interface_index] = {}
                    interfaces[interface_index][oid_name] = interface_value

        # Post-process the interface data
        processed_interfaces = {}
        for interface_index, interface in interfaces.items():
            interface["is_up"] = interface.pop("ifOperStatus") == "1"
            interface["is_enabled"] = interface.pop("ifAdminStatus") == "1"
            interface["description"] = interface.pop("ifDescr")
            interface["last_flapped"] = -1.0  # SNMP doesn't provide this data
            interface["speed"] = (
                float(interface.pop("ifSpeed", 0)) / 1000000.0
            )  # Convert speed from bps to Mbps
            interface["mtu"] = int(interface.pop("ifMtu", 0))

            if "ifPhysAddress" in interface:
                phys_addr = interface.pop("ifPhysAddress")
                interface["mac_address"] = ":".join(
                    [f"{ord(c):02x}" for c in phys_addr]
                )
            else:
                interface["mac_address"] = ""

            interface_name = interface["description"]
            processed_interfaces[interface_name] = interface

        return processed_interfaces
