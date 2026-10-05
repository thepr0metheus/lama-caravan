#!/usr/bin/env python3
"""Only the explicit board action may spend a saved subscription reset."""
import ast
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent

class ResetSpendGuard:
    def check(self):
        errors=[]
        for path in (ROOT/'caravan').rglob('*.py'):
            rel=path.relative_to(ROOT).as_posix()
            for node in ast.walk(ast.parse(path.read_text())):
                if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr=='consume':
                    obj=node.func.value
                    if isinstance(obj,ast.Call) and isinstance(obj.func,ast.Name) and obj.func.id=='SubscriptionResetDesk' and rel!='caravan/admin/routes.py':
                        errors.append(f'{rel}:{node.lineno}: automatic reset spending is forbidden')
                if isinstance(node,ast.Constant) and isinstance(node.value,str) and '/wham/rate-limit-reset-credits/consume' in node.value and rel!='caravan/admin/subscription_resets.py':
                    errors.append(f'{rel}:{node.lineno}: reset transport belongs to SubscriptionResetDesk')
        for path in (ROOT/'static/js').glob('*.js'):
            if '"/api/cloud-accounts/subscription-reset"' in path.read_text() and path.name!='subscription-resets.js':
                errors.append(f'{path.name}: reset POST belongs to the confirmed reset action')
        return errors

if __name__=='__main__':
    errors=ResetSpendGuard().check()
    print('Subscription reset boundary: '+('; '.join(errors) if errors else 'OK'))
    sys.exit(bool(errors))
