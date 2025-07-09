from app import create_app, db
from app.models import Action

# Créer une instance de l'app Flask
app = create_app()

# Liste des actions
action_names = [
  "Add data", "Analyze data", "Annotate data", "Anonymize data", "Archive data",
  "Clean data", "Cluster data", "Collect data", "Compare data", "Convert data",
  "Create data", "Delete data", "Encrypt data", "Export data", "Filter data",
  "Import data", "Index data", "Integrate data", "Link data", "Merge data",
  "Mine data", "Model data", "Normalize data", "Organize data", "Process data",
  "Protect data", "Pseudonymize data", "Report data", "Secure data", "Share data",
  "Store data", "Summarize data"
]

# Contexte d'application pour accéder à la BDD
with app.app_context():
    for name in action_names:
        if not Action.query.filter_by(nom=name).first():
            db.session.add(Action(nom=name))
    db.session.commit()
    print("✅ Actions ajoutées à la base de données.")
