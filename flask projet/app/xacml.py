import os
from lxml import etree
from flask import current_app


def generate_xacml_file_from_profil(profil_data, output_dir):
    """
    Génère un fichier XACML au format XML pour un profil donné.
    profil_data est un dict avec:
        - profil_id
        - profil_nom
        - actions_permises (liste de strings)
        - types_champs_visibles (liste de strings)
    """
    NS = "urn:oasis:names:tc:xacml:3.0:core:schema:wd-17"
    nsmap = {None: NS}

    # Élément racine Policy
    policy = etree.Element("Policy", nsmap=nsmap,
                           PolicyId=f"Policy-{profil_data['profil_id']}",
                           RuleCombiningAlgId="deny-overrides")

    # Cible : Target (Subject + Resources + Environments)
    target = etree.SubElement(policy, "Target")

    # Sujet (profil)
    subjects = etree.SubElement(target, "Subjects")
    subject = etree.SubElement(subjects, "Subject")
    attr_subject = etree.SubElement(subject, "Attribute",
                                    AttributeId="profil:nom",
                                    IncludeInResult="false")
    attr_val_subject = etree.SubElement(attr_subject, "AttributeValue",
                                        DataType="http://www.w3.org/2001/XMLSchema#string")
    attr_val_subject.text = profil_data.get('profil_nom', 'UnknownProfil')

    # Ressources (actions permises)
    resources = etree.SubElement(target, "Resources")
    for action in profil_data.get('actions_permises', []):
        resource = etree.SubElement(resources, "Resource")
        attr_action = etree.SubElement(resource, "Attribute",
                                       AttributeId="action:nom",
                                       IncludeInResult="false")
        attr_val_action = etree.SubElement(attr_action, "AttributeValue",
                                           DataType="http://www.w3.org/2001/XMLSchema#string")
        attr_val_action.text = action

    # Environments (types de champs visibles)
    environments = etree.SubElement(target, "Environments")
    for champ_type in profil_data.get('types_champs_visibles', []):
        environment = etree.SubElement(environments, "Environment")
        attr_env = etree.SubElement(environment, "Attribute",
                                    AttributeId="champ:type",
                                    IncludeInResult="false")
        attr_val_env = etree.SubElement(attr_env, "AttributeValue",
                                        DataType="http://www.w3.org/2001/XMLSchema#string")
        attr_val_env.text = champ_type

    # Règle autorisante
    etree.SubElement(policy, "Rule", RuleId="rule-1", Effect="Permit")

    # Écriture du fichier XML
    xml_bytes = etree.tostring(policy, pretty_print=True,
                               xml_declaration=True, encoding="UTF-8")

    os.makedirs(output_dir, exist_ok=True)
    filename = f"policy_{profil_data['profil_id']}.xml"
    filepath = os.path.join(output_dir, filename)
    with open(filepath, "wb") as f:
        f.write(xml_bytes)

    return filepath


def generate_and_save_all_xacml_from_mongo():
    """
    Parcourt tous les profils dans MongoDB, génère et sauvegarde un fichier XACML par profil
    """
    mongo_db = current_app.mongo_db
    collection = mongo_db['profils_rules']

    xacml_dir = os.path.join(current_app.root_path, 'xacml_rules')
    os.makedirs(xacml_dir, exist_ok=True)

    profils = collection.find()
    saved_files = []

    for profil in profils:
        filepath = generate_xacml_file_from_profil(profil, xacml_dir)
        saved_files.append(filepath)

    return saved_files
