import React, {Component} from "react";
import ReactDOM from "react-dom";
import axios from 'axios';

const StateIcon = (props) => {
    const {state} = props;
    if (state === 'running') {
        return <i className="glyphicon glyphicon-flash text-warning" />;
    }
    else if (state === 'fail') {
        return <i className="glyphicon glyphicon-remove-circle text-danger" />;
    }
    else if (state === 'success') {
        return <i className="glyphicon glyphicon-ok-circle text-success" />;
    }
    else if (state === 'complete') {
        return <i className="glyphicon glyphicon-ok text-info" />;
    }
    return state;
};


class LogItem extends Component {
    constructor (props) {
        super(props);
        this.state = {
            outputShown: true,
        };
        this.toggleOutput = this.toggleOutput.bind(this);
    }

    toggleOutput() {
        this.setState(prevState => ({
            outputShown: !prevState.outputShown,
        }));
    };

    componentWillUpdate(prevProps){
        if (prevProps.state !== this.props.state) {
            this.setState({outputShown: false});
        }
    }

    render (){
        return (
            <div id={"logItem_" + this.props.id} className="log-item">
                <div className="row">
                    <div className="col-md-10">
                        <p className={"command command-" + this.props.state}>
                            <StateIcon state={this.props.state}/>
                            <span className="host"> root@{this.props.server}:~# </span>{this.props.action}
                        </p>
                    </div>
                    <div className="col-md-2" onClick={this.toggleOutput}>
                        { this.state.outputShown
                            ? <span className="label label-default" style={{cursor: "pointer"}}>hide log</span>
                            : <span className="label label-default" style={{cursor: "pointer"}}>show log</span>
                        }
                    </div>
                </div>

                <pre id={"pre_"+this.props.id} className={this.state.outputShown ? "": "hidden"}>{this.props.output}</pre>
            </div>
        );
    }
}

class LogContainer extends Component {

    constructor(props) {
        super(props);
        this.state = {
            items: this.props.items
        }
    }

    scrollToBottom() {
        const node = ReactDOM.findDOMNode(this.logEnd);
        node.scrollIntoView({ behavior: "smooth" });
    }

    componentDidMount() {
        this.scrollToBottom();
    }

    componentDidUpdate() {
        this.scrollToBottom();
    }


    render() {
        const logItems = this.props.items.map(itemInfo => {
            const {id, action, state, output} = itemInfo;
            return (
                <LogItem
                    key={id}
                    id={id}
                    action={action}
                    state={state}
                    output={output}
                    server={this.props.server}
                />
            );

        });

        return (
            <div className={this.props.show ? "log-body" : "hidden"}>
                {logItems}
                <div style={{ float:"left", clear: "both" }} ref={(el) => { this.logEnd = el; }}></div>
            </div>
        )
    }
}

class Logger extends Component {
    constructor(props) {
        super(props);
        this.state = {
            logData: {
                messages: []
            },
            showContent: true
        };
        this.fetchData = this.fetchData.bind(this);
        this.toggleContentView = this.toggleContentView.bind(this);
    }

    componentDidMount() {
        this.timerID = setInterval(
            () => this.fetchData(),
            500
        );
    }

    fetchData() {
        const id = document.clustermgr.task_id;
        axios.get("/log/" + id).then(
            (response) => {
                this.setState({logData: response.data});
                if (response.data.state === 'SUCCESS' || response.data.state === 'FAILED') {
                    clearInterval(this.timerID);
                }
            }
        );
    }

    componentWillUnmount() {
        clearInterval(this.timerID);
    }

    toggleContentView(){
        this.setState(prevState => ({showContent: !prevState.showContent}))
    }

    render() {
        return (
            <div className="logger">
                <div className="row log-header">
                    <div className="col-md-8">
                    </div>
                    <div className="col-md-4">
                        { this.state.showContent
                            ?
                            <button className={"logger-button pull-right"} onClick={this.toggleContentView}>
                            <i className="glyphicon glyphicon-eye-close"/>  Hide Logs</button>
                            :
                            <button className={"logger-button pull-right"} onClick={this.toggleContentView}>
                                <i className="glyphicon glyphicon-eye-open"/>  Show Logs</button>
                        }
                    </div>
                </div>
                <LogContainer items={this.state.logData.messages} show={this.state.showContent} server={"example.com"}/>
            </div>
        )

    }
}

ReactDOM.render(
    <Logger/>,
    document.getElementById('log_root')
);
