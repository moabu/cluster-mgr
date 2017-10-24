import React, {Component} from "react";
import ReachDOM from "react-dom";


/**
 *
 *  log_item {
 *      id: unique_id,
 *      action: command being run or any action,
 *      state: pending, success, fail,
 *      output: any value returned by the action
 *  }
 *
 *  log_container {
 *      // container that hold a number of log_items
 *  }
 *
 *  app{
 *     // holds the the conatiner or multiple containers if necessary
 *  }
 *
 *
 */
const LogItem = ({id, action, state, output, server}) => {
    const getState = () => {
        if (state === 'running'){
            return <i className="glyphicon glyphicon-flash text-warning"></i>;
        }
        else if (state === 'fail'){
            return <i className="glyphicon glyphicon-remove-circle text-danger"></i>;
        }
        else if (state === 'success'){
            return <i className="glyphicon glyphicon-ok-circle text-success"></i>;
        }
        return state;
    };
    return (
        <div id={"logItem_"+id} className="log-item">
            <p className={"command command-"+state}>{getState()} <span className="host">root@{server}:~# </span>{action}</p>
            <pre>{output}</pre>
        </div>
    );
};

const LogContainer = (props) => {
    const {items, title, server} = props;
    const logItems = items.map(itemInfo => {
        const {id, action, state, output} = itemInfo;

        return (
            <LogItem
                key={id}
                id={id}
                action={action}
                state={state}
                output={output}
                server={server}
            />
        );

    });

    return (
        <div className="log-body">
            {logItems}
        </div>
    );
};

class Logger extends Component {
    constructor (props) {
        super(props);

    }

    render() {
        const logData = [
            {id:1, action: 'apt-get update -y', state: "success", output: "update succeded"},
            {id:2, action: 'service solserver restart', state: "fail", output: "Service restarted"},
            {id:3, action: 'apt-get install stunnel', state: "success", output: "something \n that has \n a multi-line \n output"},
            {id:4, action: 'apt-get install redis-server', state: "running", output: "some output being streamed"},
        ];
        const server = "example.com";
        return (
            <div className="logger">
                <div className="row log-header">
                    <div className="col-md-8">
                        <h5>{"Setting up server : " + server}</h5>
                    </div>
                    <div className="col-md-4">
                    </div>
                </div>
                <LogContainer items={logData} server={server}/>;
            </div>
        )

    }
}

ReachDOM.render(
    <Logger/>,
    document.getElementById('log_root')
);
